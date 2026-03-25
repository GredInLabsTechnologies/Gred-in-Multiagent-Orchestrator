import pytest
import os
import json
import hashlib
from pathlib import Path
from fastapi.testclient import TestClient
from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.app_session_service import AppSessionService
from tools.gimo_server.config import get_settings

def _auth(role: str):
    return lambda: AuthContext(token="t", role=role)

@pytest.fixture
def session_with_repo(test_client, tmp_path):
    app.dependency_overrides[verify_token] = _auth("operator")
    
    # Create session
    res = test_client.post("/ops/app/sessions", json={})
    session_id = res.json()["id"]
    
    # Create a dummy repo with one file
    repo_dir = tmp_path / "dummy_repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("print('hello')", encoding="utf-8")
    
    # Create a dummy registry pointing to tmp repo
    settings = get_settings()
    registry_path = settings.repo_registry_path
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps({"repos": [str(repo_dir.resolve())]}))
    
    # Get handle
    mapping = AppSessionService.get_handle_mapping()
    repo_handle = None
    for handle, path in mapping.items():
        if str(Path(path).resolve()) == str(repo_dir.resolve()):
            repo_handle = handle
            break
    
    assert repo_handle is not None
    
    # Bind repo
    test_client.post(f"/ops/app/sessions/{session_id}/repo/select", json={"repo_id": repo_handle})
    
    yield session_id, repo_handle
    
    app.dependency_overrides.clear()

def test_recon_generates_read_proofs(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    files = res.json()
    file_handle = [f["handle"] for f in files if f["type"] == "file"][0]
    
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/read/{file_handle}")
    assert res.status_code == 200
    data = res.json()
    assert "proof" in data
    assert data["proof"]["kind"] == "read"
    assert "evidence_hash" in data["proof"]

def test_recon_returns_opaque_handles_not_host_paths(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    files = res.json()
    for f in files:
        assert len(f["handle"]) == 16
        assert ":" not in f["handle"]
        assert "/" not in f["name"]
        assert "\\" not in f["name"]

def test_recon_scope_is_bound_to_repo_handle_or_session_bind(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")
    res = test_client.post("/ops/app/sessions", json={})
    session_id = res.json()["id"]
    
    # Negative test: No repo bound
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    assert res.status_code == 400
    assert "no repository bound" in res.json()["detail"].lower()

def test_validated_task_requires_evidence_hash(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    # Negative: No evidence
    res = test_client.post(f"/ops/app/sessions/{session_id}/drafts", json={
        "acceptance_criteria": "Gate 5A",
        "allowed_paths": ["app.py"]
    })
    assert res.status_code == 403
    
    # Provide evidence
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    file_handle = res.json()[0]["handle"]
    test_client.get(f"/ops/app/sessions/{session_id}/recon/read/{file_handle}")
    
    res = test_client.post(f"/ops/app/sessions/{session_id}/drafts", json={
        "acceptance_criteria": "Gate 5A",
        "allowed_paths": ["app.py"]
    })
    assert res.status_code == 200
    assert "evidence_hash" in res.json()["validated_task_spec"]

def test_validated_task_emits_context_pack_and_allowed_paths(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    # Recon first
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    file_handle = res.json()[0]["handle"]
    test_client.get(f"/ops/app/sessions/{session_id}/recon/read/{file_handle}")
    
    res = test_client.post(f"/ops/app/sessions/{session_id}/drafts", json={
        "acceptance_criteria": "Check context pack",
        "allowed_paths": ["app.py"]
    })
    data = res.json()
    assert "repo_context_pack" in data
    assert "allowed_paths" in data["validated_task_spec"]
    assert "app.py" in data["validated_task_spec"]["allowed_paths"]

def test_context_request_service_persists_pending_request(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    res = test_client.post(f"/ops/app/sessions/{session_id}/context-requests", json={
        "description": "More context please"
    })
    assert res.status_code == 200
    req_id = res.json()["id"]
    
    res = test_client.get(f"/ops/app/sessions/{session_id}/context-requests")
    assert any(r["id"] == req_id and r["status"] == "pending" for r in res.json())

def test_context_request_service_can_mark_request_resolved_or_cancelled(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    res = test_client.post(f"/ops/app/sessions/{session_id}/context-requests", json={"description": "Task 1"})
    id1 = res.json()["id"]
    res = test_client.post(f"/ops/app/sessions/{session_id}/context-requests", json={"description": "Task 2"})
    id2 = res.json()["id"]
    
    # Resolve 1
    test_client.post(f"/ops/app/sessions/{session_id}/context-requests/{id1}/resolve", json={"evidence": "Done"})
    # Cancel 2
    test_client.post(f"/ops/app/sessions/{session_id}/context-requests/{id2}/cancel", json={"reason": "Abort"})
    
    res = test_client.get(f"/ops/app/sessions/{session_id}/context-requests")
    statuses = {r["id"]: r["status"] for r in res.json()}
    assert statuses[id1] == "resolved"
    assert statuses[id2] == "cancelled"

def test_app_surface_recon_flow_uses_real_service_not_stub(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    # If it was a stub, it wouldn't return real files from tmp_path
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    assert any(f["name"] == "app.py" for f in res.json())

def test_app_payload_never_leaks_host_path(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    payload = json.dumps(res.json())
    # tmp_path on windows usually contains 'Temp' or similar, but we check for absolute root patterns
    assert "C:\\" not in payload
    assert "Users\\" not in payload
    # Handles should be hashes
    for f in res.json():
        assert len(f["handle"]) == 16

def test_recon_without_bound_repo_is_rejected(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")
    res = test_client.post("/ops/app/sessions", json={})
    session_id = res.json()["id"]
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    assert res.status_code == 400

def test_draft_validation_without_evidence_is_rejected(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    res = test_client.post(f"/ops/app/sessions/{session_id}/drafts", json={
        "acceptance_criteria": "Fail",
        "allowed_paths": []
    })
    assert res.status_code == 403
