from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.ops_models import OpsApproved, OpsDraft, OpsRun, PolicyDecision
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext


def _override_auth() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


@pytest.fixture
def client():
    app.dependency_overrides[verify_token] = _override_auth
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_phase4_create_draft_rejects_when_risk_too_high(monkeypatch, client):
    from tools.gimo_server.routers.ops import plan_router

    monkeypatch.setattr(
        plan_router.RuntimePolicyService,
        "evaluate_draft_policy",
        lambda **_: PolicyDecision(
            policy_decision_id="p1",
            decision="allow",
            status_code="POLICY_ALLOW",
            policy_hash_expected="h1",
            policy_hash_runtime="h1",
            triggered_rules=[],
        ),
    )

    body = {
        "objective": "Actualizar modulo de runtime",
        "constraints": ["No romper API"],
        "acceptance_criteria": ["Compila sin errores"],
        "repo_context": {
            "target_branch": "main",
            "path_scope": ["tools/gimo_server/services/file_service.py"],
        },
        "execution": {
            "intent_class": "SAFE_REFACTOR",
            "risk_score": 88,
        },
    }

    res = client.post("/ops/drafts", json=body)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "rejected"
    assert data["error"] == "RISK_SCORE_TOO_HIGH"
    assert data["context"]["execution_decision"] == "RISK_SCORE_TOO_HIGH"


def test_phase4_approve_blocks_when_risk_too_high(monkeypatch, client):
    from tools.gimo_server.routers.ops import run_router

    draft = OpsDraft(
        id="d_phase4",
        prompt="p",
        context={"execution_decision": "RISK_SCORE_TOO_HIGH"},
        status="draft",
    )

    monkeypatch.setattr(run_router.OpsService, "get_draft", lambda _id: draft)

    res = client.post("/ops/drafts/d_phase4/approve")
    assert res.status_code == 409
    assert res.json()["detail"] == "RISK_SCORE_TOO_HIGH"


def test_phase4_approve_disables_auto_run_when_not_eligible(monkeypatch, client):
    from tools.gimo_server.routers.ops import run_router

    draft = OpsDraft(
        id="d_phase4",
        prompt="p",
        context={"execution_decision": "HUMAN_APPROVAL_REQUIRED"},
        status="draft",
    )
    approved = OpsApproved(
        id="a_phase4",
        draft_id="d_phase4",
        prompt="p",
        content="ok",
    )
    called = {"create_run": False}

    monkeypatch.setattr(run_router.OpsService, "get_draft", lambda _id: draft)
    monkeypatch.setattr(run_router.OpsService, "approve_draft", lambda *_args, **_kwargs: approved)
    monkeypatch.setattr(run_router.OpsService, "create_run", lambda _approved_id: called.__setitem__("create_run", True))

    res = client.post("/ops/drafts/d_phase4/approve?auto_run=true")
    assert res.status_code == 200
    data = res.json()
    assert data["run"] is None
    assert called["create_run"] is False


def test_phase4_approve_auto_run_enters_running_immediately(monkeypatch, client):
    from tools.gimo_server.routers.ops import run_router

    draft = OpsDraft(
        id="d_phase4_auto",
        prompt="p",
        context={"execution_decision": "AUTO_RUN_ELIGIBLE"},
        status="draft",
    )
    approved = OpsApproved(
        id="a_phase4_auto",
        draft_id="d_phase4_auto",
        prompt="p",
        content="ok",
    )
    created_run = OpsRun(
        id="r_phase4_auto",
        approved_id="a_phase4_auto",
        status="pending",
    )
    updated_run = OpsRun(
        id="r_phase4_auto",
        approved_id="a_phase4_auto",
        status="running",
    )

    monkeypatch.setattr(run_router.OpsService, "get_draft", lambda _id: draft)
    monkeypatch.setattr(run_router.OpsService, "approve_draft", lambda *_args, **_kwargs: approved)
    monkeypatch.setattr(run_router.OpsService, "create_run", lambda _approved_id: created_run)
    monkeypatch.setattr(run_router.OpsService, "update_run_status", lambda *_a, **_k: updated_run)

    def _capture_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(run_router.asyncio, "create_task", _capture_task)

    res = client.post("/ops/drafts/d_phase4_auto/approve?auto_run=true")
    assert res.status_code == 200
    data = res.json()
    assert data["run"] is not None
    assert data["run"]["status"] == "running"


def test_phase4_prompt_mode_allows_missing_intent_class_in_context(client):
    body = {
        "prompt": "haz cambios pequeños",
        "context": {"source": "chat"},
    }

    res = client.post("/ops/drafts", json=body)
    assert res.status_code == 201


def test_phase4_create_run_returns_409_when_active_run_exists(monkeypatch, client):
    from tools.gimo_server.routers.ops import run_router

    monkeypatch.setattr(
        run_router.OpsService,
        "create_run",
        lambda _approved_id: (_ for _ in ()).throw(RuntimeError("RUN_ALREADY_ACTIVE:r_active_1")),
    )

    res = client.post("/ops/runs", json={"approved_id": "a_phase4"})
    assert res.status_code == 409
    assert res.json()["detail"].startswith("RUN_ALREADY_ACTIVE")


def test_phase4_rerun_returns_201_and_links_source(monkeypatch, client):
    from tools.gimo_server.routers.ops import run_router

    rerun = OpsRun(
        id="r_new_1",
        approved_id="a_phase4",
        status="pending",
        run_key="r_key_1",
        rerun_of="r_old_1",
        attempt=2,
    )

    monkeypatch.setattr(run_router.OpsService, "rerun", lambda _run_id: rerun)
    monkeypatch.setattr(run_router.OpsService, "update_run_status", lambda *_a, **_k: rerun)

    res = client.post("/ops/runs/r_old_1/rerun")
    assert res.status_code == 201
    body = res.json()
    assert body["id"] == "r_new_1"
    assert body["rerun_of"] == "r_old_1"
    assert body["attempt"] == 2


def test_phase4_rerun_returns_409_when_active_instance_exists(monkeypatch, client):
    from tools.gimo_server.routers.ops import run_router

    def _raise_active(_run_id: str):
        raise RuntimeError("RUN_ALREADY_ACTIVE:r_active_1")

    monkeypatch.setattr(run_router.OpsService, "rerun", _raise_active)

    res = client.post("/ops/runs/r_old_1/rerun")
    assert res.status_code == 409
    assert res.json()["detail"].startswith("RUN_ALREADY_ACTIVE")


def test_phase4_rerun_returns_409_when_source_run_is_active(monkeypatch, client):
    from tools.gimo_server.routers.ops import run_router

    def _raise_source_active(_run_id: str):
        raise RuntimeError("RERUN_SOURCE_ACTIVE:r_old_1")

    monkeypatch.setattr(run_router.OpsService, "rerun", _raise_source_active)

    res = client.post("/ops/runs/r_old_1/rerun")
    assert res.status_code == 409
    assert res.json()["detail"].startswith("RERUN_SOURCE_ACTIVE")


def test_phase4_create_run_maps_invalid_fsm_to_422(monkeypatch, client):
    from tools.gimo_server.routers.ops import run_router

    def _raise_invalid(_approved_id: str):
        raise RuntimeError("INVALID_FSM_TRANSITION:running->pending")

    monkeypatch.setattr(run_router.OpsService, "create_run", _raise_invalid)

    res = client.post("/ops/runs", json={"approved_id": "a_phase4"})
    assert res.status_code == 422
    assert res.json()["detail"].startswith("INVALID_FSM_TRANSITION")
