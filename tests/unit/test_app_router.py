from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext

def _auth(role: str):
    return lambda: AuthContext(token="t", role=role)

def test_session_lifecycle_via_router(test_client):
    """Prueba el ciclo create/list/select/get/purge de la sesión de App vía REST."""
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
    assert session_id is not None

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
    """Verifica errores honestos para sesiones inexistentes."""
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

def test_app_execute_run_route_uses_backend_service(test_client):
    """Verifica que /ops/app/runs/{run_id}/execute delega al backend canónico."""
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
    """Verifica que /ops/app/runs/{run_id}/review refleja el payload backend-authored."""
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
        base_commit="base123",
        head_commit="head123",
        changed_files=["app.py"],
        drift_detected=False,
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
        "bundle": {
            "base_commit": "base123",
            "head_commit": "head123",
            "changed_files": ["app.py"],
            "drift_detected": False,
        },
    }
    mock_preview.assert_called_once_with("run_123")
    mock_bundle.assert_called_once_with("run_123")

def test_app_discard_route_returns_backend_purge_receipt(test_client):
    """Verifica que /ops/app/runs/{run_id}/discard devuelve el recibo canónico de PurgeService."""
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
        "tools.gimo_server.routers.ops.app_router.PurgeService.purge_run",
        return_value=receipt,
    ) as mock_purge:
        res = test_client.post("/ops/app/runs/run_123/discard")

    assert res.status_code == 200
    assert res.json() == {
        "status": "ok",
        "receipt": receipt.model_dump(),
    }
    mock_purge.assert_called_once_with("run_123")

def test_actions_safe_logic_hardened():
    """P4H-4: Prueba directamente el guard de _is_actions_safe_request con paths dinámicos."""
    from tools.gimo_server.main import _is_actions_safe_request
    from unittest.mock import MagicMock
    
    # Replicamos el contrato de ops_routes
    actions_safe_targets = {
        ("GET", "/ops/app/repos"),
        ("POST", "/ops/app/sessions"),
        ("GET", "/ops/app/sessions/{id}"),
        ("POST", "/ops/app/sessions/{id}/repo/select"),
        ("POST", "/ops/app/sessions/{id}/purge"),
    }
    
    # Casos Positivos
    for method, path in [
        ("GET", "/ops/app/repos"),
        ("POST", "/ops/app/sessions"),
        ("GET", "/ops/app/sessions/any-session-id"),
        ("POST", "/ops/app/sessions/sess_123/repo/select"),
        ("POST", "/ops/app/sessions/abc/purge"),
    ]:
        req = MagicMock()
        req.method = method
        req.url.path = path
        assert _is_actions_safe_request(req, actions_safe_targets), f"Debería ser safe: {method} {path}"
    
    # Casos Negativos: Método incorrecto
    req = MagicMock()
    req.method = "DELETE"
    req.url.path = "/ops/app/sessions/abc/purge"
    assert not _is_actions_safe_request(req, actions_safe_targets)
    
    # Casos Negativos: Número de segmentos (más)
    req = MagicMock()
    req.method = "GET"
    req.url.path = "/ops/app/sessions/abc/extra"
    assert not _is_actions_safe_request(req, actions_safe_targets)
    
    # Casos Negativos: Número de segmentos (menos)
    req = MagicMock()
    req.method = "POST"
    req.url.path = "/ops/app/sessions/repo/select" # Falta el {id}
    assert not _is_actions_safe_request(req, actions_safe_targets)
    
    # Casos Negativos: Prefijo incorrecto
    req = MagicMock()
    req.method = "GET"
    req.url.path = "/ops/other/sessions/abc"
    assert not _is_actions_safe_request(req, actions_safe_targets)
