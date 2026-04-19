"""R17 Cluster A — Dead Pipeline Worker tests.

Covers:
- _spawn_run returns task and acks (no synchronous failure)
- run_worker reclaims stale `running` runs via OpsService.update_run_status
- policy_gate / risk_gate run regardless of approved_id (no silent skip)
- engine_service asserts planned_stages == executed_stages on done finalization
- merge_gate run passes the invariant with zero LLM tokens (no llm_execute stage)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.gimo_server.engine.contracts import StageInput
from tools.gimo_server.engine.stages.policy_gate import PolicyGate
from tools.gimo_server.engine.stages.risk_gate import RiskGate
from tools.gimo_server.services.execution.engine_service import EngineService


# ---------------------------------------------------------------------------
# Gates: must run even when approved_id is set
# ---------------------------------------------------------------------------
class _FakeDecision:
    def __init__(self, decision="allow"):
        self.decision = decision
        self.status_code = 200
        self.reason = "ok"

    def model_dump(self):
        return {"decision": self.decision, "status_code": 200, "reason": "ok"}


class _FakeIntentAudit:
    def __init__(self):
        self.execution_decision = "AUTO_RUN_ELIGIBLE"

    def model_dump(self):
        return {
            "execution_decision": "AUTO_RUN_ELIGIBLE",
            "intent_effective": "SAFE_REFACTOR",
            "risk_score": 5.0,
        }


@pytest.mark.asyncio
async def test_policy_gate_runs_under_approved_id():
    """approved_id must NOT cause the gate to silently skip evaluation."""
    with patch("tools.gimo_server.engine.stages.policy_gate.RuntimePolicyService") as mock_policy, \
         patch("tools.gimo_server.engine.stages.policy_gate.IntentClassificationService") as mock_intent:
        mock_policy.evaluate_draft_policy.return_value = _FakeDecision("allow")
        mock_intent.evaluate.return_value = _FakeIntentAudit()

        gate = PolicyGate()
        inp = StageInput(
            run_id="r1",
            context={
                "approved_id": "a_xyz",
                "path_scope": ["src/main.py"],
                "intent_declared": "SAFE_REFACTOR",
                "risk_score": 5.0,
            },
        )
        result = await gate.execute(inp)

        mock_policy.evaluate_draft_policy.assert_called_once()
        mock_intent.evaluate.assert_called_once()

    assert result.status == "continue"
    assert "gate_skipped" not in result.artifacts
    assert result.artifacts.get("pre_approved") is True


@pytest.mark.asyncio
async def test_risk_gate_runs_under_approved_id():
    gate = RiskGate()
    inp = StageInput(
        run_id="r1",
        context={"approved_id": "a_xyz"},
        artifacts={"intent_audit": {"intent_effective": "SAFE_REFACTOR", "risk_score": 5.0}},
    )
    result = await gate.execute(inp)
    assert result.status == "continue"
    assert "gate_skipped" not in result.artifacts
    assert result.artifacts.get("pre_approved") is True


# ---------------------------------------------------------------------------
# _spawn_run: returns task, raises on synchronous failure
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_spawn_run_returns_task_and_acks():
    """_spawn_run must create a real task and return it without raising."""
    from tools.gimo_server.routers.ops import run_router

    fake_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    async def _fake_execute(run_id, composition=None):
        await asyncio.sleep(0.01)
        return []

    with patch.object(run_router.EngineService, "execute_run", side_effect=_fake_execute):
        task = run_router._spawn_run(fake_request, "r_test_ack")

    assert isinstance(task, asyncio.Task)
    assert not task.done() or task.exception() is None
    # Drain
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Run worker: reclaims stale running runs via update_run_status
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_worker_reclaims_stale_running():
    from tools.gimo_server.services.execution import run_worker as rw_mod

    stale_run = SimpleNamespace(
        id="r_stale",
        status="running",
        heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=300),
        started_at=None,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=600),
    )
    fresh_run = SimpleNamespace(
        id="r_fresh",
        status="running",
        heartbeat_at=datetime.now(timezone.utc),
        started_at=None,
        created_at=datetime.now(timezone.utc),
    )

    worker = rw_mod.RunWorker()

    with patch.object(rw_mod.OpsService, "get_runs_by_status", return_value=[stale_run, fresh_run]), \
         patch.object(rw_mod.OpsService, "update_run_status") as mock_update:
        worker._reclaim_stale_running_runs()

    # Stale reclaimed via update_run_status -> pending; fresh untouched.
    calls = [c for c in mock_update.call_args_list if c.args[:2] == ("r_stale", "pending")]
    assert calls, f"expected reclaim call, got {mock_update.call_args_list}"
    fresh_calls = [c for c in mock_update.call_args_list if c.args[0] == "r_fresh"]
    assert not fresh_calls


# ---------------------------------------------------------------------------
# Engine service: planned-stages invariant
# ---------------------------------------------------------------------------
def test_engine_service_planned_stage_names_includes_all_compositions():
    """Every composition must yield a non-empty planned-stage list."""
    for comp in EngineService._COMPOSITION_MAP:
        names = EngineService._planned_stage_names(comp)
        assert names, f"composition {comp} produced empty planned stages"


@pytest.mark.asyncio
async def test_engine_service_asserts_planned_stages_executed():
    """If a stage is silently skipped, finalization must mark the run failed."""
    from tools.gimo_server.services.execution import engine_service as eng_mod

    fake_run = SimpleNamespace(
        id="r_invariant",
        status="running",
        approved_id=None,
        validated_task_spec=None,
        child_context=None,
        child_prompt=None,
        parent_run_id=None,
        child_run_ids=[],
        awaiting_count=0,
    )

    # Pipeline that pretends to succeed but executes ZERO stages.
    async def _fake_run_composition(comp, run_id, ctx, on_stage_transition=None):
        # Do not call on_stage_transition — simulates silent-skip class of bugs.
        return [SimpleNamespace(status="continue", artifacts={}, error=None, caused_by=None)]

    captured = {}

    def _capture_status(run_id, status, msg=None):
        captured["status"] = status
        captured["msg"] = msg or ""
        return fake_run

    with patch("tools.gimo_server.services.ops.OpsService") as mock_ops, \
         patch.object(EngineService, "run_composition", side_effect=_fake_run_composition):
        mock_ops.get_run.return_value = fake_run
        mock_ops.get_approved.return_value = None
        mock_ops.get_draft.return_value = None
        mock_ops.OPS_DIR = MagicMock()
        mock_ops._gics = None
        mock_ops.update_run_status.side_effect = _capture_status
        mock_ops.append_log = MagicMock()
        mock_ops.heartbeat_run = MagicMock()

        await EngineService.execute_run("r_invariant", composition="merge_gate")

    assert captured.get("status") == "error"
    assert "silent_skip_error" in captured.get("msg", "")


@pytest.mark.asyncio
async def test_merge_gate_run_passes_invariant_with_zero_tokens():
    """merge_gate has no llm_execute stage; honest-run invariant must accept it."""
    from tools.gimo_server.services.execution import engine_service as eng_mod

    fake_run = SimpleNamespace(
        id="r_merge",
        status="running",
        approved_id=None,
        validated_task_spec=None,
        child_context=None,
        child_prompt=None,
        parent_run_id=None,
        child_run_ids=[],
        awaiting_count=0,
    )

    planned = EngineService._planned_stage_names("merge_gate")
    assert "llm_execute" not in planned, "merge_gate must NOT contain llm_execute"

    async def _fake_run_composition(comp, run_id, ctx, on_stage_transition=None):
        # Faithfully fire the hook for every planned stage — what a real
        # merge_gate run does, with zero LLM token usage.
        for name in planned:
            if on_stage_transition:
                on_stage_transition(name, "start")
                on_stage_transition(name, "end")
        return [SimpleNamespace(status="continue", artifacts={}, error=None, caused_by=None)
                for _ in planned]

    captured = {}

    def _capture_status(run_id, status, msg=None):
        captured["status"] = status
        captured["msg"] = msg or ""
        return fake_run

    with patch("tools.gimo_server.services.ops.OpsService") as mock_ops, \
         patch.object(EngineService, "run_composition", side_effect=_fake_run_composition):
        mock_ops.get_run.return_value = fake_run
        mock_ops.get_approved.return_value = None
        mock_ops.get_draft.return_value = None
        mock_ops.OPS_DIR = MagicMock()
        mock_ops._gics = None
        mock_ops.update_run_status.side_effect = _capture_status
        mock_ops.append_log = MagicMock()
        mock_ops.heartbeat_run = MagicMock()

        await EngineService.execute_run("r_merge", composition="merge_gate")

    assert captured.get("status") == "done", f"got status={captured.get('status')} msg={captured.get('msg')}"
