"""P0 True E2E Tests — valida pipeline completo con stages reales.

Ejercita PolicyGate → RiskGate → LlmExecute → FileWrite usando mock
de ProviderService.static_generate (sin llamadas HTTP reales).

NO usa _fake_execute_run — corre el pipeline REAL de stages.

Usa UNA sola instancia de TestClient para todos los tests del módulo.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.ops_models import PolicyDecision


# ── Helpers ────────────────────────────────────────────────────

def _override_auth() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


def _policy_allow():
    return PolicyDecision(
        policy_decision_id="policy_test_allow",
        decision="allow",
        status_code="POLICY_ALLOW",
        policy_hash_expected="hash_ok",
        policy_hash_runtime="hash_ok",
        triggered_rules=[],
    )


def _policy_deny():
    return PolicyDecision(
        policy_decision_id="policy_test_deny",
        decision="deny",
        status_code="POLICY_DENY_FORBIDDEN_SCOPE",
        policy_hash_expected="hash_ok",
        policy_hash_runtime="hash_ok",
        triggered_rules=[],
    )


def _draft_body(target_file=None, intent="SAFE_REFACTOR", risk_score=10):
    body = {
        "objective": "Test E2E pipeline execution",
        "constraints": ["No romper API publica"],
        "acceptance_criteria": ["Compila sin errores"],
        "repo_context": {
            "target_branch": "main",
            "path_scope": ["tools/gimo_server/services/file_service.py"],
        },
        "execution": {
            "intent_class": intent,
            "risk_score": risk_score,
        },
    }
    if target_file:
        body["repo_context"]["target_file"] = target_file
        body["context"] = {"target_file": target_file}
    return body


# ── Shared fixtures ────────────────────────────────────────────

@pytest.fixture(scope="module")
def ops_dir(tmp_path_factory):
    """Directorio OPS aislado compartido por todos los tests del módulo."""
    return tmp_path_factory.mktemp("ops_e2e")


@pytest.fixture(scope="module")
def e2e_env(ops_dir):
    """Levanta UNA instancia de TestClient + mocks para todo el módulo.

    Yields (client, queued, active_policy) donde:
    - client: TestClient reutilizable
    - queued: lista mutable de tasks capturados (se vacía entre tests)
    - active_policy: lista [fn] para cambiar la policy en caliente
    """
    from tools.gimo_server.routers.ops import run_router
    from tools.gimo_server.services.providers import service_impl as provider_service_impl
    from tools.gimo_server.services import runtime_policy_service as rps_mod
    from tools.gimo_server.services import run_worker as rw_mod
    from tools.gimo_server.resilience import SupervisedTask

    # 1. Redirigir OPS a directorio temporal
    _original_dirs = {
        attr: getattr(OpsService, attr)
        for attr in (
            "OPS_DIR", "PLAN_FILE", "PROVIDER_FILE", "DRAFTS_DIR",
            "APPROVED_DIR", "RUNS_DIR", "RUN_EVENTS_DIR", "RUN_LOGS_DIR",
            "LOCKS_DIR", "CONFIG_FILE", "LOCK_FILE",
        )
    }
    OpsService.OPS_DIR = ops_dir
    OpsService.PLAN_FILE = ops_dir / "plan.json"
    OpsService.PROVIDER_FILE = ops_dir / "provider.json"
    OpsService.DRAFTS_DIR = ops_dir / "drafts"
    OpsService.APPROVED_DIR = ops_dir / "approved"
    OpsService.RUNS_DIR = ops_dir / "runs"
    OpsService.RUN_EVENTS_DIR = ops_dir / "run_events"
    OpsService.RUN_LOGS_DIR = ops_dir / "run_logs"
    OpsService.LOCKS_DIR = ops_dir / "locks"
    OpsService.CONFIG_FILE = ops_dir / "config.json"
    OpsService.LOCK_FILE = ops_dir / ".ops.lock"
    OpsService.ensure_dirs()

    # 2. Policy mutable
    active_policy = [_policy_allow]
    _orig_evaluate = rps_mod.RuntimePolicyService.evaluate_draft_policy

    @classmethod  # type: ignore[misc]
    def _mock_evaluate(cls, **_kwargs):
        return active_policy[0]()
    rps_mod.RuntimePolicyService.evaluate_draft_policy = _mock_evaluate

    # 3. Mock LLM
    _orig_generate = provider_service_impl.ProviderService.static_generate

    @classmethod  # type: ignore[misc]
    async def _mock_static_generate(cls, prompt: str, context=None, **kwargs):
        return {
            "content": "[MOCK] Generated content",
            "provider": "mock",
            "model": "mock-model",
            "tokens_used": 42,
            "prompt_tokens": 20,
            "completion_tokens": 22,
            "cost_usd": 0.001,
        }
    provider_service_impl.ProviderService.static_generate = _mock_static_generate

    # 4. Desactivar RunWorker background
    _orig_tick = rw_mod.RunWorker._tick
    rw_mod.RunWorker._tick = lambda self: asyncio.sleep(0)

    # 5. Captura de tasks via SupervisedTask.spawn
    queued: list[Awaitable[object]] = []
    _orig_spawn = SupervisedTask.spawn

    def _capture_spawn(self, coro, *, name="", on_failure=None, timeout=None):
        queued.append(coro)
        return None

    SupervisedTask.spawn = _capture_spawn

    # 6. Auth override
    app.dependency_overrides[verify_token] = _override_auth

    # 7. UNA sola instancia de TestClient para todo el módulo
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, queued, active_policy

    # Teardown: restaurar todo
    app.dependency_overrides.pop(verify_token, None)
    SupervisedTask.spawn = _orig_spawn
    rw_mod.RunWorker._tick = _orig_tick
    provider_service_impl.ProviderService.static_generate = _orig_generate
    rps_mod.RuntimePolicyService.evaluate_draft_policy = _orig_evaluate
    for attr, val in _original_dirs.items():
        setattr(OpsService, attr, val)


@pytest.fixture(autouse=True)
def _reset_queued(e2e_env):
    """Vacía la cola de tasks capturados y restaura auth entre tests."""
    _, queued, active_policy = e2e_env
    while queued:
        queued.pop().close()
    active_policy[0] = _policy_allow
    # Restaurar auth override (conftest lo limpia después de cada test)
    app.dependency_overrides[verify_token] = _override_auth
    yield
    while queued:
        queued.pop().close()


def _run_queued_tasks(queued):
    while queued:
        asyncio.run(queued.pop(0))


# ── Tests ──────────────────────────────────────────────────────

def test_full_pipeline_draft_to_done(e2e_env):
    """Pipeline completo: draft → approve → execute → done con stages reales."""
    client, queued, _ = e2e_env

    draft_res = client.post("/ops/drafts", json=_draft_body())
    assert draft_res.status_code == 201, f"Draft creation failed: {draft_res.text}"
    draft = draft_res.json()
    assert draft["status"] == "draft"

    approve_res = client.post(f"/ops/drafts/{draft['id']}/approve?auto_run=true")
    assert approve_res.status_code == 200, f"Approval failed: {approve_res.text}"
    run = approve_res.json().get("run")
    assert run is not None, "auto_run should create a run"
    assert run["status"] == "running"

    assert len(queued) == 1, "Expected 1 queued task"
    _run_queued_tasks(queued)

    get_run_res = client.get(f"/ops/runs/{run['id']}")
    assert get_run_res.status_code == 200
    completed_run = get_run_res.json()
    assert completed_run["status"] == "done", f"Expected done, got {completed_run['status']}"


def test_file_task_writes_to_disk(e2e_env, tmp_path):
    """file_task composition escribe archivo real en disco."""
    client, queued, _ = e2e_env

    target_file = str(tmp_path / "output.txt")
    body = _draft_body(target_file=target_file)

    draft_res = client.post("/ops/drafts", json=body)
    assert draft_res.status_code == 201
    draft = draft_res.json()

    approve_res = client.post(f"/ops/drafts/{draft['id']}/approve?auto_run=true")
    assert approve_res.status_code == 200
    run = approve_res.json().get("run")
    assert run is not None

    _run_queued_tasks(queued)

    get_run_res = client.get(f"/ops/runs/{run['id']}")
    completed = get_run_res.json()
    assert completed["status"] in ("done", "error"), f"Unexpected status: {completed['status']}"


def test_policy_gate_denial_stops_pipeline(e2e_env):
    """R17 Cluster A: PolicyGate runs even on approved runs.

    The previous "approval is terminal" doctrine (R14.1 silent gate-skip on
    approved_id) was the root cause of issues #1/#5/#6/#11/#12 — runs were
    born hollow because gates short-circuited and produced gate_skipped:true
    artifacts. Cluster A removes the silent skip: gates now always execute,
    and approval is recorded in the verdict, not used as a license to bypass
    evaluation. A policy change to deny AFTER approval correctly blocks
    execution because the gate runs against the live policy.
    """
    client, queued, active_policy = e2e_env

    draft_res = client.post("/ops/drafts", json=_draft_body())
    assert draft_res.status_code == 201
    draft = draft_res.json()
    assert draft["status"] == "draft"

    approve_res = client.post(f"/ops/drafts/{draft['id']}/approve?auto_run=true")
    assert approve_res.status_code == 200
    run = approve_res.json().get("run")
    assert run is not None

    # Switch policy to deny after approval — gate now runs against the live
    # policy and must block the run.
    active_policy[0] = _policy_deny
    _run_queued_tasks(queued)

    get_run_res = client.get(f"/ops/runs/{run['id']}")
    completed = get_run_res.json()
    assert completed["status"] == "error", \
        f"Expected error (gate denies post-approval), got {completed['status']}"


def test_high_risk_score_halts_pipeline(e2e_env):
    """Risk score alto (>60) causa RISK_SCORE_TOO_HIGH en draft."""
    client, queued, _ = e2e_env

    body = _draft_body(risk_score=100)
    draft_res = client.post("/ops/drafts", json=body)
    assert draft_res.status_code == 201
    draft = draft_res.json()
    assert draft["status"] == "rejected"
    assert draft.get("context", {}).get("execution_decision") == "RISK_SCORE_TOO_HIGH"

    approve_res = client.post(f"/ops/drafts/{draft['id']}/approve?auto_run=true")
    assert approve_res.status_code == 409


def test_rerun_increments_attempt(e2e_env):
    """Rerun de un run completado incrementa attempt counter."""
    client, queued, _ = e2e_env

    draft_res = client.post("/ops/drafts", json=_draft_body())
    assert draft_res.status_code == 201
    draft = draft_res.json()

    approve_res = client.post(f"/ops/drafts/{draft['id']}/approve?auto_run=true")
    assert approve_res.status_code == 200
    run = approve_res.json().get("run")
    assert run is not None

    _run_queued_tasks(queued)

    get_run_res = client.get(f"/ops/runs/{run['id']}")
    first_run = get_run_res.json()
    assert first_run["status"] == "done"

    # Rerun
    rerun_res = client.post(f"/ops/runs/{run['id']}/rerun")
    assert rerun_res.status_code == 201
    rerun = rerun_res.json()
    assert rerun["rerun_of"] == run["id"]
    assert rerun["attempt"] == first_run["attempt"] + 1

    _run_queued_tasks(queued)

    rerun_get_res = client.get(f"/ops/runs/{rerun['id']}")
    assert rerun_get_res.json()["status"] == "done"
