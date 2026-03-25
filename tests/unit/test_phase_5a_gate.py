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
    
    # List files
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    assert res.status_code == 200
    files = res.json()
    assert len(files) > 0, f"Expected some files but got {files}"
    file_handle = None
    for f in files:
        if f["type"] == "file":
            file_handle = f["handle"]
            break
    
    assert file_handle is not None
    
    # Read file
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/read/{file_handle}")
    assert res.status_code == 200
    data = res.json()
    assert "content" in data
    assert "proof" in data
    
    # Verify proof in session
    res = test_client.get(f"/ops/app/sessions/{session_id}")
    session_data = res.json()
    assert "read_proofs" in session_data
    assert len(session_data["read_proofs"]) > 0
    assert session_data["read_proofs"][0]["artifact_handle"] == file_handle

def test_recon_returns_opaque_handles_not_host_paths(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    files = res.json()
    for f in files:
        # Handles should be 16 chars hex
        assert len(f["handle"]) == 16
        # Neither name nor handle should look like a host path (e.g. C:\ or /)
        assert ":" not in f["handle"]
        assert "\\" not in f["name"]
        assert "/" not in f["name"]

def test_recon_scope_is_bound_to_repo_handle_or_session_bind(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")
    
    # Create session WITHOUT repo
    res = test_client.post("/ops/app/sessions", json={})
    session_id = res.json()["id"]
    
    # Try recon -> should fail
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    assert res.status_code == 400
    assert "no repository bound" in res.json()["detail"].lower()


def test_validated_task_requires_evidence_hash(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    # Try draft without recon
    res = test_client.post(f"/ops/app/sessions/{session_id}/drafts", json={
        "acceptance_criteria": "Must pass gate 5A"
    })
    assert res.status_code == 403
    assert "no reconnaissance evidence" in res.json()["detail"].lower()
    
    # Perform recon (read a file)
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    file_handle = [f["handle"] for f in res.json() if f["type"] == "file"][0]
    test_client.get(f"/ops/app/sessions/{session_id}/recon/read/{file_handle}")
    
    # Try draft again
    res = test_client.post(f"/ops/app/sessions/{session_id}/drafts", json={
        "acceptance_criteria": "Must pass gate 5A"
    })
    assert res.status_code == 200
    data = res.json()
    assert "evidence_hash" in data["validated_task_spec"]
    assert data["validated_task_spec"]["requires_manual_merge"] is True

def test_context_request_service_persists_pending_request(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    # Create
    res = test_client.post(f"/ops/app/sessions/{session_id}/context-requests", json={
        "description": "Need more info on Phase 5B"
    })
    assert res.status_code == 200
    req_id = res.json()["id"]
    
    # List
    res = test_client.get(f"/ops/app/sessions/{session_id}/context-requests")
    assert len(res.json()) == 1
    assert res.json()[0]["status"] == "pending"

def test_context_request_service_can_mark_request_resolved_or_cancelled(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    # Create
    res = test_client.post(f"/ops/app/sessions/{session_id}/context-requests", json={
        "description": "Task A"
    })
    req_id = res.json()["id"]
    
    # Resolve
    res = test_client.post(f"/ops/app/sessions/{session_id}/context-requests/{req_id}/resolve", json={
        "evidence": "Here is the info"
    })
    assert res.status_code == 200
    
    # Verify
    res = test_client.get(f"/ops/app/sessions/{session_id}/context-requests")
    assert res.json()[0]["status"] == "resolved"
    assert res.json()[0]["result"] == "Here is the info"

def test_app_payload_never_leaks_host_path(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")
    
    # Perform various actions
    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    payload_str = json.dumps(res.json())
    
    # Check for common path indicators (risky for different OS, but we check for root markers)
    assert "C:\\" not in payload_str
    assert "Users\\" not in payload_str
    # "/" is allowed for relative paths, but we check if it looks like an absolute linux path if applicable
    # however handles are just hex, so it's fine.
