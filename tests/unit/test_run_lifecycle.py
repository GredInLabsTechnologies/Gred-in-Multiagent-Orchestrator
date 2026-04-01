"""Phase 7 consolidated tests.

Merged from:
- test_phase7_hardening.py (3 tests)
- test_phase7_merge_gate.py (18 tests)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.ops_models import OpsApproved, OpsDraft
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services import skills_service, notification_service, custom_plan_service
from tools.gimo_server.services.merge_gate_service import MergeGateService
from tools.gimo_server.services.ops_service import OpsService


def _override_auth() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


# ── Shared helpers ──────────────────────────────────────────


def _setup_ops_dirs(tmp_path):
    OpsService.OPS_DIR = tmp_path / "ops"
    OpsService.DRAFTS_DIR = OpsService.OPS_DIR / "drafts"
    OpsService.APPROVED_DIR = OpsService.OPS_DIR / "approved"
    OpsService.RUNS_DIR = OpsService.OPS_DIR / "runs"
    OpsService.LOCKS_DIR = OpsService.OPS_DIR / "locks"
    OpsService.CONFIG_FILE = OpsService.OPS_DIR / "config.json"
    OpsService.LOCK_FILE = OpsService.OPS_DIR / ".ops.lock"
    OpsService.ensure_dirs()


def _seed_draft_and_approved(*, draft_id: str = "d1", approved_id: str = "a1", risk_score: float = 10.0):
    draft = OpsDraft(
        id=draft_id,
        prompt="p",
        context={
            "repo_context": {"target_branch": "main", "repo_id": "repoA"},
            "commit_base": "abc123",
            "risk_score": risk_score,
            "intent_effective": "SAFE_REFACTOR",
            "source_ref": "HEAD",
            "policy_decision": "allow",
            "policy_decision_id": "pd-1",
        },
        status="draft",
    )
    approved = OpsApproved(
        id=approved_id,
        draft_id=draft_id,
        prompt="p",
        content="c",
    )
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    OpsService._approved_path(approved.id).write_text(approved.model_dump_json(indent=2), encoding="utf-8")
    return draft, approved


def _valid_skill_payload(command: str = "/hardened") -> dict:
    return {
        "name": "Hardened Skill",
        "description": "Verification skill",
        "command": command,
        "replace_graph": False,
        "nodes": [
            {"id": "orch", "type": "orchestrator"},
            {"id": "worker_1", "type": "worker", "data": {"label": "Worker 1", "prompt": "Test"}},
        ],
        "edges": [
            {"source": "orch", "target": "worker_1"},
        ],
    }


# ── Hardening tests (from test_phase7_hardening.py) ─────────


def _provision_merge_gate_contract(monkeypatch, tmp_path):
    from tools.gimo_server.services import merge_gate_service as mgs

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mgs, "resolve_workspace_path", lambda *args, **kwargs: workspace)
    monkeypatch.setattr(mgs, "resolve_authoritative_repo_path", lambda *args, **kwargs: workspace)
    return workspace


@pytest.fixture
def client():
    app.dependency_overrides[verify_token] = _override_auth
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_skill_execution_sse_events(tmp_path, monkeypatch, client):
    """Verify that executing a skill triggers NotificationService.publish."""
    monkeypatch.setattr(skills_service, "SKILLS_DIR", tmp_path / "skills")

    mock_publish = AsyncMock()
    monkeypatch.setattr(notification_service.NotificationService, "publish", mock_publish)

    mock_plan = custom_plan_service.CustomPlan(
        id="test_plan",
        name="Test Plan",
        status="done",
        nodes=[],
        edges=[]
    )
    monkeypatch.setattr(custom_plan_service.CustomPlanService, "execute_plan", AsyncMock(return_value=mock_plan))

    create_res = client.post("/ops/skills", json=_valid_skill_payload())
    assert create_res.status_code == 201
    skill_id = create_res.json()["id"]

    exec_res = client.post(f"/ops/skills/{skill_id}/execute", json={"replace_graph": False})
    assert exec_res.status_code == 201

    await asyncio.sleep(0.5)

    event_types = [call.args[0] for call in mock_publish.call_args_list]
    assert "skill_execution_started" in event_types
    assert "skill_execution_finished" in event_types


@pytest.mark.slow
@pytest.mark.asyncio
async def test_skill_execution_error_propagation(tmp_path, monkeypatch, client):
    """Verify that an error in execution emits a finished event with error status."""
    monkeypatch.setattr(skills_service, "SKILLS_DIR", tmp_path / "skills")

    mock_publish = AsyncMock()
    monkeypatch.setattr(notification_service.NotificationService, "publish", mock_publish)

    monkeypatch.setattr(custom_plan_service.CustomPlanService, "execute_plan", AsyncMock(side_effect=Exception("Simulated Failure")))

    create_res = client.post("/ops/skills", json=_valid_skill_payload("/fail"))
    assert create_res.status_code == 201
    skill_id = create_res.json()["id"]

    client.post(f"/ops/skills/{skill_id}/execute", json={"replace_graph": False})
    await asyncio.sleep(0.5)

    finished_call = next((c for c in mock_publish.call_args_list if c.args[0] == "skill_execution_finished"), None)
    assert finished_call is not None
    assert finished_call.args[1]["status"] == "error"
    assert "Simulated Failure" in finished_call.args[1]["message"]


def test_slugify_uniqueness_under_load():
    """Fast check that slugify generates unique IDs even when called rapidly."""
    ids = set()
    for _ in range(1000):
        ids.add(skills_service.SkillsService._slugify_id("Test Name"))
    assert len(ids) == 1000


# ── Merge gate tests (from test_phase7_merge_gate.py) ───────


def test_phase7_create_run_conflicts_when_active_run_exists(tmp_path):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d1", approved_id="a1")

    run1 = OpsService.create_run(approved.id)

    with pytest.raises(RuntimeError) as exc:
        OpsService.create_run(approved.id)

    assert str(exc.value).startswith("RUN_ALREADY_ACTIVE")
    assert run1.run_key is not None


def test_phase7_create_run_creates_new_instance_after_terminal(tmp_path):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d1t", approved_id="a1t")

    run1 = OpsService.create_run(approved.id)
    OpsService.update_run_status(run1.id, "done", msg="completed")

    run2 = OpsService.create_run(approved.id)

    assert run1.id != run2.id
    assert run1.run_key == run2.run_key


def test_phase7_approve_draft_is_idempotent(tmp_path):
    _setup_ops_dirs(tmp_path)
    draft = OpsDraft(id="d_appr", prompt="p", context={}, status="draft")
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    appr1 = OpsService.approve_draft(draft.id, approved_by="op")
    appr2 = OpsService.approve_draft(draft.id, approved_by="op")

    assert appr1.id == appr2.id
    assert appr1.draft_id == draft.id
    assert len([a for a in OpsService.list_approved() if a.draft_id == draft.id]) == 1


def test_phase7_approve_draft_canonicalizes_legacy_structured_content(tmp_path):
    _setup_ops_dirs(tmp_path)
    legacy_plan = {
        "id": "plan_1",
        "title": "Plan",
        "objective": "Objective",
        "tasks": [
            {
                "id": "t1",
                "title": "Investigate",
                "description": "Read the module",
                "depends": [],
                "status": "pending",
                "agent_assignee": {
                    "role": "researcher",
                    "model": "gpt-4o",
                    "system_prompt": "Review carefully.",
                },
            }
        ],
    }
    draft = OpsDraft(
        id="d_structured",
        prompt="p",
        context={"structured": True},
        content=json.dumps(legacy_plan, indent=2),
        status="draft",
    )
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    approved = OpsService.approve_draft(draft.id, approved_by="op")
    approved_payload = json.loads(approved.content)
    persisted_draft = OpsService.get_draft(draft.id)

    assert approved_payload["tasks"][0]["task_descriptor"]["task_id"] == "t1"
    assert "task_fingerprint" in approved_payload["tasks"][0]
    assert persisted_draft is not None
    assert json.loads(persisted_draft.content)["tasks"][0]["task_fingerprint"] == approved_payload["tasks"][0]["task_fingerprint"]


def test_phase7_create_draft_canonicalizes_structured_plan_content(tmp_path):
    _setup_ops_dirs(tmp_path)
    legacy_plan = {
        "id": "plan_1",
        "title": "Plan",
        "objective": "Objective",
        "tasks": [
            {
                "id": "t1",
                "title": "Investigate",
                "description": "Read the module",
                "depends": [],
                "status": "pending",
                "agent_assignee": {
                    "role": "researcher",
                    "model": "gpt-4o",
                    "system_prompt": "Review carefully.",
                },
            }
        ],
    }

    draft = OpsService.create_draft(
        prompt="p",
        context={"structured": True},
        content=json.dumps(legacy_plan, indent=2),
    )

    payload = json.loads(draft.content)
    assert payload["tasks"][0]["task_descriptor"]["task_id"] == "t1"
    assert "task_fingerprint" in payload["tasks"][0]


def test_phase7_rerun_creates_new_instance_with_parent_link(tmp_path):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d_rerun", approved_id="a_rerun")

    run1 = OpsService.create_run(approved.id)
    OpsService.update_run_status(run1.id, "done", msg="completed")

    run2 = OpsService.rerun(run1.id)

    assert run2.id != run1.id
    assert run2.rerun_of == run1.id
    assert run2.run_key == run1.run_key
    assert run2.attempt == run1.attempt + 1


def test_phase7_rerun_conflicts_when_source_key_has_active_instance(tmp_path):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d_rerun_active", approved_id="a_rerun_active")

    run1 = OpsService.create_run(approved.id)

    with pytest.raises(RuntimeError) as exc:
        OpsService.rerun(run1.id)

    assert str(exc.value).startswith("RERUN_SOURCE_ACTIVE")


def test_phase7_cancel_then_rerun_creates_new_attempt(tmp_path):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d_cancel_rerun", approved_id="a_cancel_rerun")

    run1 = OpsService.create_run(approved.id)
    OpsService.update_run_status(run1.id, "cancelled", msg="operator cancelled")

    run2 = OpsService.rerun(run1.id)

    assert run2.id != run1.id
    assert run2.rerun_of == run1.id
    assert run2.attempt == run1.attempt + 1
    assert run2.status == "pending"


def test_phase7_merge_lock_ttl_heartbeat_and_recovery(tmp_path):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d2", approved_id="a2")
    run = OpsService.create_run(approved.id)

    lock = OpsService.acquire_merge_lock("repoA", run.id, ttl_seconds=2)
    assert lock["run_id"] == run.id

    lock2 = OpsService.heartbeat_merge_lock("repoA", run.id, ttl_seconds=2)
    assert lock2["run_id"] == run.id

    lock_file = OpsService._merge_lock_path("repoA")
    payload = __import__("json").loads(lock_file.read_text(encoding="utf-8"))
    payload["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    lock_file.write_text(__import__("json").dumps(payload), encoding="utf-8")

    recovered = OpsService.recover_stale_lock("repoA")
    assert recovered is True


def test_phase7_generic_execution_lock_ttl_heartbeat_and_recovery(tmp_path):
    _setup_ops_dirs(tmp_path)

    lock = OpsService.acquire_execution_lock(
        "thread_execution",
        "thread_A",
        "owner_1",
        ttl_seconds=2,
        metadata={"thread_id": "thread_A"},
    )
    assert lock["owner_id"] == "owner_1"
    assert lock["resource_id"] == "thread_A"

    lock2 = OpsService.heartbeat_execution_lock(
        "thread_execution",
        "thread_A",
        "owner_1",
        ttl_seconds=2,
    )
    assert lock2["owner_id"] == "owner_1"

    with pytest.raises(RuntimeError):
        OpsService.acquire_execution_lock("thread_execution", "thread_A", "owner_2", ttl_seconds=30)

    lock_file = OpsService._execution_lock_path("thread_execution", "thread_A")
    payload = __import__("json").loads(lock_file.read_text(encoding="utf-8"))
    payload["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    lock_file.write_text(__import__("json").dumps(payload), encoding="utf-8")

    recovered = OpsService.recover_stale_execution_lock("thread_execution", "thread_A")
    assert recovered is True

    lock3 = OpsService.acquire_execution_lock("thread_execution", "thread_A", "owner_2", ttl_seconds=30)
    assert lock3["owner_id"] == "owner_2"


def test_phase7_merge_gate_lock_conflict_sets_merge_locked(tmp_path, monkeypatch):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d3", approved_id="a3")
    run = OpsService.create_run(approved.id)
    _provision_merge_gate_contract(monkeypatch, tmp_path)

    OpsService.acquire_merge_lock("repoA", "other_run", ttl_seconds=30)

    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "MERGE_LOCKED"


def test_phase7_merge_gate_tests_failure_sets_validation_failed_tests(tmp_path, monkeypatch):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d4", approved_id="a4")
    run = OpsService.create_run(approved.id)

    from tools.gimo_server.services import merge_gate_service as mgs
    _provision_merge_gate_contract(monkeypatch, tmp_path)

    monkeypatch.setattr(mgs.GitService, "is_worktree_clean", lambda _base: True)
    monkeypatch.setattr(mgs.GitService, "run_tests", lambda _base: (False, "tests failed"))
    monkeypatch.setattr(mgs.GitService, "run_lint_typecheck", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "dry_run_merge", lambda _b, _s, _t: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "get_head_commit", lambda _base: "abc")
    monkeypatch.setattr(mgs.GitService, "perform_merge", lambda _b, _s, _t: (True, "ok"))

    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "VALIDATION_FAILED_TESTS"


def test_phase7_merge_gate_lint_failure_sets_validation_failed_lint(tmp_path, monkeypatch):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d7", approved_id="a7")
    run = OpsService.create_run(approved.id)

    from tools.gimo_server.services import merge_gate_service as mgs
    _provision_merge_gate_contract(monkeypatch, tmp_path)

    monkeypatch.setattr(mgs.GitService, "is_worktree_clean", lambda _base: True)
    monkeypatch.setattr(mgs.GitService, "run_tests", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "run_lint_typecheck", lambda _base: (False, "lint failed"))

    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "VALIDATION_FAILED_LINT"


def test_phase7_merge_gate_dry_run_conflict_sets_merge_conflict(tmp_path, monkeypatch):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d8", approved_id="a8")
    run = OpsService.create_run(approved.id)

    from tools.gimo_server.services import merge_gate_service as mgs
    _provision_merge_gate_contract(monkeypatch, tmp_path)

    monkeypatch.setattr(mgs.GitService, "is_worktree_clean", lambda _base: True)
    monkeypatch.setattr(mgs.GitService, "run_tests", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "run_lint_typecheck", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "dry_run_merge", lambda _b, _s, _t: (False, "conflict"))

    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "MERGE_CONFLICT"


def test_phase7_merge_gate_detects_baseline_tamper(tmp_path):
    _setup_ops_dirs(tmp_path)
    draft, approved = _seed_draft_and_approved(draft_id="d5", approved_id="a5")
    draft.context["policy_hash_expected"] = "hash_a"
    draft.context["policy_hash_runtime"] = "hash_b"
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    run = OpsService.create_run(approved.id)
    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "BASELINE_TAMPER_DETECTED"


def test_phase7_merge_gate_risk_60_is_hard_block(tmp_path):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d6", approved_id="a6", risk_score=60.0)
    run = OpsService.create_run(approved.id)
    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "RISK_SCORE_TOO_HIGH"


def test_phase7_merge_gate_requires_policy_decision_id(tmp_path):
    _setup_ops_dirs(tmp_path)
    draft, approved = _seed_draft_and_approved(draft_id="d9", approved_id="a9")
    draft.context.pop("policy_decision_id", None)
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    run = OpsService.create_run(approved.id)
    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "WORKER_CRASHED_RECOVERABLE"


def test_phase7_merge_gate_policy_review_requires_human(tmp_path):
    _setup_ops_dirs(tmp_path)
    draft, approved = _seed_draft_and_approved(draft_id="d10", approved_id="a10")
    draft.context["policy_decision"] = "review"
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    run = OpsService.create_run(approved.id)
    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "HUMAN_APPROVAL_REQUIRED"


def test_phase7_merge_gate_missing_intent_defaults_low_risk_path(tmp_path):
    _setup_ops_dirs(tmp_path)
    draft, approved = _seed_draft_and_approved(draft_id="d11", approved_id="a11")
    draft.context.pop("intent_effective", None)
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    run = OpsService.create_run(approved.id)
    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is False
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status in ("pending", "running")


def test_phase7_merge_gate_post_merge_failure_triggers_rollback(tmp_path, monkeypatch):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d12", approved_id="a12")
    run = OpsService.create_run(approved.id)

    from tools.gimo_server.services import merge_gate_service as mgs
    _provision_merge_gate_contract(monkeypatch, tmp_path)

    monkeypatch.setattr(mgs.GitService, "is_worktree_clean", lambda _base: True)
    monkeypatch.setattr(mgs.GitService, "run_tests", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "run_lint_typecheck", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "dry_run_merge", lambda _b, _s, _t: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "perform_merge", lambda _b, _s, _t: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "rollback_to_commit", lambda _b, _c: (True, "rollback ok"))

    calls = {"n": 0}

    def _head(_base):
        calls["n"] += 1
        if calls["n"] == 1:
            return "abc_before"
        raise RuntimeError("cannot read HEAD after merge")

    monkeypatch.setattr(mgs.GitService, "get_head_commit", _head)

    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    awaiting = OpsService.get_run(run.id)
    assert awaiting is not None
    assert awaiting.status == "AWAITING_MERGE"

    ok = asyncio.run(MergeGateService.perform_manual_merge(run.id))
    assert ok is False
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "ROLLBACK_EXECUTED"


def test_ops_service_list_drafts_filters_limit_offset(tmp_path):
    _setup_ops_dirs(tmp_path)

    now = datetime.now(timezone.utc)

    drafts = [
        OpsDraft(id="d_a", prompt="a", status="draft", created_at=now - timedelta(minutes=3)),
        OpsDraft(id="d_b", prompt="b", status="approved", created_at=now - timedelta(minutes=2)),
        OpsDraft(id="d_c", prompt="c", status="draft", created_at=now - timedelta(minutes=1)),
        OpsDraft(id="d_d", prompt="d", status="rejected", created_at=now),
    ]
    for item in drafts:
        OpsService._draft_path(item.id).write_text(item.model_dump_json(indent=2), encoding="utf-8")

    only_draft = OpsService.list_drafts(status="draft")
    assert [d.id for d in only_draft] == ["d_c", "d_a"]

    paged = OpsService.list_drafts(status="draft", offset=1, limit=1)
    assert [d.id for d in paged] == ["d_a"]
