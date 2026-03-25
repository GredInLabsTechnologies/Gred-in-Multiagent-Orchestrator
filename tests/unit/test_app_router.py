import pytest
from fastapi.testclient import TestClient
from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.app_session_service import AppSessionService

def _auth(role: str):
    return lambda: AuthContext(token="t", role=role)

def test_session_lifecycle_via_router(test_client):
    """Prueba el ciclo de vida de la sesión de App mediante endpoints REST."""
    app.dependency_overrides[verify_token] = _auth("operator")
    
    # Create
    res = test_client.post("/ops/app/sessions", json={"metadata": {"tag": "app_test"}})
    assert res.status_code == 200
    session_id = res.json()["id"]
    assert session_id is not None
    
    # Get
    res = test_client.get(f"/ops/app/sessions/{session_id}")
    assert res.status_code == 200
    assert res.json()["metadata"]["tag"] == "app_test"
    
    # Purge
    res = test_client.post(f"/ops/app/sessions/{session_id}/purge")
    assert res.status_code == 200
    assert res.json()["deleted"] == session_id
    
    # Verify purged
    res = test_client.get(f"/ops/app/sessions/{session_id}")
    assert res.status_code == 404
    
    app.dependency_overrides.clear()

def test_repo_selection_with_handles(test_client):
    """Verifica que la selección de repo use handles y no paths."""
    app.dependency_overrides[verify_token] = _auth("operator")
    
    # Create session
    res = test_client.post("/ops/app/sessions", json={})
    session_id = res.json()["id"]
    
    # Select Invalid Repo (un handle que no existe en el registry)
    res = test_client.post(f"/ops/app/sessions/{session_id}/repo/select", json={"repo_id": "invalid_handle"})
    assert res.status_code == 400
    
    # Verificamos dummies honestos (P4)
    res = test_client.post(f"/ops/app/sessions/{session_id}/drafts", json={})
    assert res.status_code == 200
    assert res.json()["status"] == "not_implemented"
    
    res = test_client.post("/ops/app/runs", json={})
    assert res.status_code == 200
    assert res.json()["status"] == "not_implemented"
    
    app.dependency_overrides.clear()

def test_actions_safe_logic_hardened():
    """P4H-4: Prueba directamente el guard de _is_actions_safe_request con paths dinámicos."""
    from tools.gimo_server.main import _is_actions_safe_request
    from unittest.mock import MagicMock
    
    # Replicamos el contrato de ops_routes
    actions_safe_targets = {
        ("POST", "/ops/app/sessions"),
        ("GET", "/ops/app/sessions/{id}"),
        ("POST", "/ops/app/sessions/{id}/repo/select"),
        ("POST", "/ops/app/sessions/{id}/purge"),
    }
    
    # Casos Positivos
    for method, path in [
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
