from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.ops_service import OpsService


def _override_auth() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


def _configure_ops_dirs(monkeypatch, tmp_path) -> None:
    ops_dir = tmp_path / "ops"
    monkeypatch.setattr(OpsService, "OPS_DIR", ops_dir)
    monkeypatch.setattr(OpsService, "PLAN_FILE", ops_dir / "plan.json")
    monkeypatch.setattr(OpsService, "PROVIDER_FILE", ops_dir / "provider.json")
    monkeypatch.setattr(OpsService, "DRAFTS_DIR", ops_dir / "drafts")
    monkeypatch.setattr(OpsService, "APPROVED_DIR", ops_dir / "approved")
    monkeypatch.setattr(OpsService, "RUNS_DIR", ops_dir / "runs")
    monkeypatch.setattr(OpsService, "RUN_EVENTS_DIR", ops_dir / "run_events")
    monkeypatch.setattr(OpsService, "RUN_LOGS_DIR", ops_dir / "run_logs")
    monkeypatch.setattr(OpsService, "LOCKS_DIR", ops_dir / "locks")
    monkeypatch.setattr(OpsService, "CONFIG_FILE", ops_dir / "config.json")
    monkeypatch.setattr(OpsService, "LOCK_FILE", ops_dir / ".ops.lock")
    OpsService.ensure_dirs()


def _draft_body() -> dict:
    return {
        "objective": "Actualizar modulo de runtime sin romper la API",
        "constraints": ["No romper API publica"],
        "acceptance_criteria": ["Compila sin errores", "Mantiene contratos existentes"],
        "repo_context": {
            "target_branch": "main",
            "path_scope": ["tools/gimo_server/services/file_service.py"],
        },
        "execution": {
            "intent_class": "SAFE_REFACTOR",
            "risk_score": 10,
        },
    }


def _install_task_capture(monkeypatch):
    from tools.gimo_server.routers.ops import plan_router, run_router
    from tools.gimo_server.ops_models import PolicyDecision

    queued: list[Awaitable[object]] = []
    original_create_task = asyncio.create_task

    async def _fake_execute_run(run_id: str, composition: str | None = None):
        del composition
        current = OpsService.get_run(run_id)
        if current and current.status == "pending":
            OpsService.update_run_status(run_id, "running", msg="Execution started via fake engine")
        OpsService.append_log(run_id, level="INFO", msg="Pipeline completed successfully")
        OpsService.update_run_status(run_id, "done", msg="Pipeline completed successfully")
        return []

    monkeypatch.setattr(
        plan_router.RuntimePolicyService,
        "evaluate_draft_policy",
        lambda **_: PolicyDecision(
            policy_decision_id="policy_test_allow",
            decision="allow",
            status_code="POLICY_ALLOW",
            policy_hash_expected="hash_ok",
            policy_hash_runtime="hash_ok",
            triggered_rules=[],
        ),
    )
    monkeypatch.setattr(run_router.EngineService, "execute_run", _fake_execute_run)

    def _capture_selected_tasks(coro):
        code = getattr(coro, "cr_code", None)
        if code and code.co_name == "_fake_execute_run":
            queued.append(coro)
            return None
        return original_create_task(coro)

    monkeypatch.setattr(run_router.asyncio, "create_task", _capture_selected_tasks)
    return queued


def _run_queued_tasks(queued: list[Awaitable[object]]) -> None:
    while queued:
        asyncio.run(queued.pop(0))


def test_p0_ops_http_lifecycle_happy_path_and_rerun(monkeypatch, tmp_path):
    _configure_ops_dirs(monkeypatch, tmp_path)
    queued = _install_task_capture(monkeypatch)
    app.dependency_overrides[verify_token] = _override_auth

    with TestClient(app, raise_server_exceptions=False) as client:
        draft_res = client.post("/ops/drafts", json=_draft_body())
        assert draft_res.status_code == 201
        draft = draft_res.json()
        assert draft["status"] == "draft"
        assert draft["context"]["execution_decision"] == "AUTO_RUN_ELIGIBLE"

        approve_res = client.post(f"/ops/drafts/{draft['id']}/approve?auto_run=true")
        assert approve_res.status_code == 200
        approval = approve_res.json()
        run = approval["run"]
        assert run is not None
        assert run["status"] == "pending"
        assert len(queued) == 1

        _run_queued_tasks(queued)

        get_run_res = client.get(f"/ops/runs/{run['id']}")
        assert get_run_res.status_code == 200
        completed_run = get_run_res.json()
        assert completed_run["status"] == "done"

        preview_res = client.get(f"/ops/runs/{run['id']}/preview")
        assert preview_res.status_code == 200
        preview = preview_res.json()
        assert preview["final_status"] == "done"
        assert "Pipeline completed successfully" in preview["diff_summary"]

        rerun_res = client.post(f"/ops/runs/{run['id']}/rerun")
        assert rerun_res.status_code == 201
        rerun = rerun_res.json()
        assert rerun["rerun_of"] == run["id"]
        assert rerun["attempt"] == completed_run["attempt"] + 1
        assert rerun["status"] == "running"
        assert len(queued) == 1

        _run_queued_tasks(queued)

        rerun_get_res = client.get(f"/ops/runs/{rerun['id']}")
        assert rerun_get_res.status_code == 200
        assert rerun_get_res.json()["status"] == "done"


def test_p0_ops_blocks_second_active_run_for_same_approved(monkeypatch, tmp_path):
    _configure_ops_dirs(monkeypatch, tmp_path)
    queued = _install_task_capture(monkeypatch)
    app.dependency_overrides[verify_token] = _override_auth

    with TestClient(app, raise_server_exceptions=False) as client:
        draft_res = client.post("/ops/drafts", json=_draft_body())
        assert draft_res.status_code == 201
        draft_id = draft_res.json()["id"]

        approve_res = client.post(f"/ops/drafts/{draft_id}/approve")
        assert approve_res.status_code == 200
        approved_id = approve_res.json()["approved"]["id"]

        run_res = client.post("/ops/runs", json={"approved_id": approved_id})
        assert run_res.status_code == 201
        first_run = run_res.json()
        assert first_run["status"] == "running"
        assert len(queued) == 1

        conflict_res = client.post("/ops/runs", json={"approved_id": approved_id})
        assert conflict_res.status_code == 409
        assert conflict_res.json()["detail"].startswith("RUN_ALREADY_ACTIVE")

        _run_queued_tasks(queued)

        final_run_res = client.get(f"/ops/runs/{first_run['id']}")
        assert final_run_res.status_code == 200
        assert final_run_res.json()["status"] == "done"
