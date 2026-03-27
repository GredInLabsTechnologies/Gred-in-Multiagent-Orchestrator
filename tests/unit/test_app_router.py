from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.lifecycle_errors import (
    LifecycleProofError,
    PurgeExecutionError,
    PurgeSafetyError,
    RunNotFoundError,
)


def _auth(role: str):
    return lambda: AuthContext(token="t", role=role)


def test_session_lifecycle_via_router(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    repos = test_client.get("/ops/app/repos")
    assert repos.status_code == 200
    repo_listing = repos.json()
    assert repo_listing
    repo_id = repo_listing[0]["repo_id"]
    assert ":" not in repo_id
    assert "\\" not in repo_id
    assert "/" not in repo_id

    res = test_client.post("/ops/app/sessions", json={"metadata": {"tag": "app_test"}})
    assert res.status_code == 200
    session_id = res.json()["id"]

    res = test_client.post(f"/ops/app/sessions/{session_id}/repo/select", json={"repo_id": repo_id})
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "repo_id": repo_id}

    res = test_client.get(f"/ops/app/sessions/{session_id}")
    assert res.status_code == 200
    assert res.json()["metadata"]["tag"] == "app_test"
    assert res.json()["repo_id"] == repo_id

    res = test_client.post(f"/ops/app/sessions/{session_id}/purge")
    assert res.status_code == 200
    assert res.json()["deleted"] == session_id

    res = test_client.get(f"/ops/app/sessions/{session_id}")
    assert res.status_code == 404


def test_missing_app_sessions_fail_honestly(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    missing_session_id = "missing-session"

    res = test_client.get(f"/ops/app/sessions/{missing_session_id}")
    assert res.status_code == 404
    assert res.json()["detail"] == "Session not found"

    res = test_client.post(f"/ops/app/sessions/{missing_session_id}/repo/select", json={"repo_id": "invalid_handle"})
    assert res.status_code == 400
    assert res.json()["detail"] == "Invalid repo_id or session"

    res = test_client.post(f"/ops/app/sessions/{missing_session_id}/purge")
    assert res.status_code == 404
    assert res.json()["detail"] == "Session not found"


def test_app_draft_route_persists_canonical_ops_draft(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    validated = {
        "validated_task_spec": {
            "base_commit": "abc123",
            "repo_handle": "repo_h",
            "allowed_paths": ["app.py"],
            "acceptance_criteria": "Make it work",
            "evidence_hash": "hash1",
            "context_pack_id": "ctx1",
            "worker_model": "gpt-4o",
            "requires_manual_merge": True,
        },
        "repo_context_pack": {
            "id": "ctx1",
            "session_id": "s1",
            "repo_handle": "repo_h",
            "base_commit": "abc123",
            "read_proofs": [],
            "allowed_paths": ["app.py"],
        },
    }
    created_draft = SimpleNamespace(id="d_123")

    with patch(
        "tools.gimo_server.routers.ops.app_router.AppSessionService.get_session",
        return_value={"id": "s1"},
    ), patch(
        "tools.gimo_server.routers.ops.app_router.DraftValidationService.validate_draft",
        return_value=validated,
    ) as mock_validate, patch(
        "tools.gimo_server.routers.ops.app_router.OpsService.create_draft",
        return_value=created_draft,
    ) as mock_create:
        res = test_client.post(
            "/ops/app/sessions/s1/drafts",
            json={"acceptance_criteria": "Make it work", "allowed_paths": ["app.py"]},
        )

    assert res.status_code == 200
    payload = res.json()
    assert payload["draft_id"] == "d_123"
    assert payload["validated_task_spec"]["repo_handle"] == "repo_h"
    mock_validate.assert_called_once()
    mock_create.assert_called_once()


def test_phase_5_routes_fail_honestly_for_missing_session(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    missing_session_id = "missing-session"

    res = test_client.get(f"/ops/app/sessions/{missing_session_id}/recon/list")
    assert res.status_code == 404
    assert res.json()["detail"] == "Session not found"

    res = test_client.get(f"/ops/app/sessions/{missing_session_id}/recon/search", params={"q": "hello"})
    assert res.status_code == 404
    assert res.json()["detail"] == "Session not found"

    res = test_client.get(f"/ops/app/sessions/{missing_session_id}/recon/read/handle123")
    assert res.status_code == 404
    assert res.json()["detail"] == "Session not found"

    res = test_client.post(
        f"/ops/app/sessions/{missing_session_id}/drafts",
        json={"acceptance_criteria": "done", "allowed_paths": ["app.py"]},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Session not found"

    res = test_client.post(
        f"/ops/app/sessions/{missing_session_id}/context-requests",
        json={"description": "need more"},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Session not found"


def test_app_execute_run_route_uses_backend_service(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    with patch(
        "tools.gimo_server.routers.ops.app_router.MergeGateService.execute_run",
        new=AsyncMock(return_value=True),
    ) as mock_execute:
        res = test_client.post("/ops/app/runs/run_123/execute")

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "run_id": "run_123"}
    mock_execute.assert_awaited_once_with("run_123")


def test_app_review_route_returns_backend_review_payload(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    preview = SimpleNamespace(
        model_dump=lambda: {
            "run_id": "run_123",
            "source_repo_head": "head123",
            "expected_base": "base123",
            "drift_detected": False,
            "manual_merge_required": True,
            "can_merge": True,
            "reason": "Ready for manual review/merge",
        }
    )
    bundle = SimpleNamespace(
        model_dump=lambda: {
            "run_id": "run_123",
            "base_commit": "base123",
            "head_commit": "head123",
            "changed_files": ["app.py"],
            "diff_summary": "diff",
            "logs": [{"msg": "tests_output_tail=PASS"}],
            "test_evidence": "PASS",
            "lint_evidence": None,
            "drift_detected": False,
            "source_repo_head": "head123",
        }
    )

    with patch(
        "tools.gimo_server.routers.ops.app_router.ReviewMergeService.get_merge_preview",
        return_value=preview,
    ) as mock_preview, patch(
        "tools.gimo_server.routers.ops.app_router.ReviewMergeService.build_review_bundle",
        return_value=bundle,
    ) as mock_bundle:
        res = test_client.get("/ops/app/runs/run_123/review")

    assert res.status_code == 200
    assert res.json() == {
        "preview": preview.model_dump(),
        "bundle": bundle.model_dump(),
    }
    mock_preview.assert_called_once_with("run_123")
    mock_bundle.assert_called_once_with("run_123")


def test_app_discard_route_returns_backend_purge_receipt(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    receipt = SimpleNamespace(
        model_dump=lambda: {
            "run_id": "run_123",
            "removed_categories": ["workspace", "logs"],
            "retained_metadata_hash": "abc123",
            "success": True,
        }
    )

    with patch(
        "tools.gimo_server.routers.ops.app_router.OpsService.discard_run",
        return_value=receipt,
    ) as mock_discard:
        res = test_client.post("/ops/app/runs/run_123/discard")

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "receipt": receipt.model_dump()}
    mock_discard.assert_called_once_with("run_123")


def test_app_discard_route_returns_honest_404_for_missing_run(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    with patch(
        "tools.gimo_server.routers.ops.app_router.OpsService.discard_run",
        side_effect=RunNotFoundError("Run run_404 not found"),
    ):
        res = test_client.post("/ops/app/runs/run_404/discard")

    assert res.status_code == 404
    assert res.json()["detail"] == "Run run_404 not found"


def test_app_review_route_returns_honest_404_for_missing_run(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    with patch(
        "tools.gimo_server.routers.ops.app_router.ReviewMergeService.get_merge_preview",
        side_effect=RunNotFoundError("Run run_404 not found"),
    ):
        res = test_client.get("/ops/app/runs/run_404/review")

    assert res.status_code == 404
    assert res.json()["detail"] == "Run run_404 not found"


def test_app_review_route_returns_honest_409_for_proof_failure(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    with patch(
        "tools.gimo_server.routers.ops.app_router.ReviewMergeService.get_merge_preview",
        side_effect=LifecycleProofError("Base commit cannot be proven"),
    ):
        res = test_client.get("/ops/app/runs/run_conflict/review")

    assert res.status_code == 409
    assert res.json()["detail"] == "Base commit cannot be proven"


def test_app_discard_route_returns_honest_409_for_repo_root_safety_failure(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    with patch(
        "tools.gimo_server.routers.ops.app_router.OpsService.discard_run",
        side_effect=PurgeSafetyError("Refusing to purge workspace because it matches repo_root: /repo"),
    ):
        res = test_client.post("/ops/app/runs/run_123/discard")

    assert res.status_code == 409
    assert "matches repo_root" in res.json()["detail"]


def test_app_discard_route_returns_honest_409_for_partial_cleanup_failure(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    with patch(
        "tools.gimo_server.routers.ops.app_router.OpsService.discard_run",
        side_effect=PurgeExecutionError("Failed to unlink logs: Permission denied"),
    ):
        res = test_client.post("/ops/app/runs/run_123/discard")

    assert res.status_code == 409
    assert res.json()["detail"] == "Failed to unlink logs: Permission denied"


def test_actions_safe_logic_hardened():
    from tools.gimo_server.main import _is_actions_safe_request
    from unittest.mock import MagicMock

    actions_safe_targets = {
        ("GET", "/ops/app/repos"),
        ("POST", "/ops/app/sessions"),
        ("GET", "/ops/app/sessions/{id}"),
        ("POST", "/ops/app/sessions/{id}/repo/select"),
        ("POST", "/ops/app/sessions/{id}/purge"),
        ("GET", "/ops/app/runs/{run_id}/review"),
        ("POST", "/ops/app/runs/{run_id}/discard"),
    }

    for method, path in [
        ("GET", "/ops/app/repos"),
        ("POST", "/ops/app/sessions"),
        ("GET", "/ops/app/sessions/any-session-id"),
        ("POST", "/ops/app/sessions/sess_123/repo/select"),
        ("POST", "/ops/app/sessions/abc/purge"),
        ("GET", "/ops/app/runs/run_123/review"),
        ("POST", "/ops/app/runs/run_123/discard"),
    ]:
        req = MagicMock()
        req.method = method
        req.url.path = path
        assert _is_actions_safe_request(req, actions_safe_targets)

    req = MagicMock()
    req.method = "DELETE"
    req.url.path = "/ops/app/sessions/abc/purge"
    assert not _is_actions_safe_request(req, actions_safe_targets)

    req = MagicMock()
    req.method = "GET"
    req.url.path = "/ops/app/sessions/abc/extra"
    assert not _is_actions_safe_request(req, actions_safe_targets)

    req = MagicMock()
    req.method = "POST"
    req.url.path = "/ops/app/sessions/repo/select"
    assert not _is_actions_safe_request(req, actions_safe_targets)

    req = MagicMock()
    req.method = "GET"
    req.url.path = "/ops/other/sessions/abc"
    assert not _is_actions_safe_request(req, actions_safe_targets)
