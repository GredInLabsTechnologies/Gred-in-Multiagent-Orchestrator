from __future__ import annotations

from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.ops_models import OpsApproved, OpsDraft, OpsRun, PolicyDecision
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext


def _override_auth() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


def test_phase4_create_draft_rejects_when_risk_too_high(monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth

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

    try:
        with TestClient(app) as client:
            res = client.post("/ops/drafts", json=body)
            assert res.status_code == 201
            data = res.json()
            assert data["status"] == "rejected"
            assert data["error"] == "RISK_SCORE_TOO_HIGH"
            assert data["context"]["execution_decision"] == "RISK_SCORE_TOO_HIGH"
    finally:
        app.dependency_overrides.clear()


def test_phase4_approve_blocks_when_risk_too_high(monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth

    from tools.gimo_server.routers.ops import run_router

    draft = OpsDraft(
        id="d_phase4",
        prompt="p",
        context={"execution_decision": "RISK_SCORE_TOO_HIGH"},
        status="draft",
    )

    monkeypatch.setattr(run_router.OpsService, "get_draft", lambda _id: draft)

    try:
        with TestClient(app) as client:
            res = client.post("/ops/drafts/d_phase4/approve")
            assert res.status_code == 409
            assert res.json()["detail"] == "RISK_SCORE_TOO_HIGH"
    finally:
        app.dependency_overrides.clear()


def test_phase4_approve_disables_auto_run_when_not_eligible(monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth

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

    try:
        with TestClient(app) as client:
            res = client.post("/ops/drafts/d_phase4/approve?auto_run=true")
            assert res.status_code == 200
            data = res.json()
            assert data["run"] is None
            assert called["create_run"] is False
    finally:
        app.dependency_overrides.clear()


def test_phase4_prompt_mode_requires_intent_class_in_context():
    app.dependency_overrides[verify_token] = _override_auth

    body = {
        "prompt": "haz cambios pequeños",
        "context": {"source": "chat"},
    }

    try:
        with TestClient(app) as client:
            res = client.post("/ops/drafts", json=body)
            assert res.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_phase4_create_run_returns_409_when_active_run_exists(monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth

    from tools.gimo_server.routers.ops import run_router

    monkeypatch.setattr(
        run_router.OpsService,
        "create_run",
        lambda _approved_id: (_ for _ in ()).throw(RuntimeError("RUN_ALREADY_ACTIVE:r_active_1")),
    )

    try:
        with TestClient(app) as client:
            res = client.post("/ops/runs", json={"approved_id": "a_phase4"})
            assert res.status_code == 409
            assert res.json()["detail"].startswith("RUN_ALREADY_ACTIVE")
    finally:
        app.dependency_overrides.clear()


def test_phase4_rerun_returns_201_and_links_source(monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth

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

    try:
        with TestClient(app) as client:
            res = client.post("/ops/runs/r_old_1/rerun")
            assert res.status_code == 201
            body = res.json()
            assert body["id"] == "r_new_1"
            assert body["rerun_of"] == "r_old_1"
            assert body["attempt"] == 2
    finally:
        app.dependency_overrides.clear()
