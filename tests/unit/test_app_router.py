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
