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
from tools.gimo_server.services.context_request_service import ContextRequestService
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
    session = AppSessionService.get_session(session_id)
    assert session is not None
    assert session["read_proofs"][0]["artifact_handle"] == file_handle
    assert session["read_proofs"][0]["evidence_hash"] == data["proof"]["evidence_hash"]

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
    assert data["repo_context_pack"]["read_proofs"][0]["artifact_handle"] == file_handle

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

def test_recon_rejects_invalid_file_handle(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")

    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/read/not-a-real-handle")
    assert res.status_code == 400
    assert "invalid file handle" in res.json()["detail"].lower()

def test_recon_search_route_returns_real_bounded_results(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")

    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/search", params={"q": "hello"})
    assert res.status_code == 200
    results = res.json()
    assert results
    assert results[0]["line"] >= 1
    assert "hello" in results[0]["content"]
    assert len(results[0]["handle"]) == 16
    assert "file" not in results[0]

def test_recon_rejects_invalid_directory_handle(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")

    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list", params={"path_handle": "not-a-real-dir"})
    assert res.status_code == 400
    assert "invalid directory handle" in res.json()["detail"].lower()

def test_recon_rejects_out_of_bounds_handle_resolution(test_client, session_with_repo, tmp_path):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")

    sibling = tmp_path / "dummy_repo_escape"
    sibling.mkdir()
    (sibling / "secret.py").write_text("print('escape')", encoding="utf-8")

    session = AppSessionService.get_session(session_id)
    session["recon_handles"] = {
        "evil-dir": "../dummy_repo_escape",
        "evil-file": "../dummy_repo_escape/secret.py",
    }
    AppSessionService._save_session(session_id, session)

    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list", params={"path_handle": "evil-dir"})
    assert res.status_code == 400
    assert "outside repository bounds" in res.json()["detail"].lower()

    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/read/evil-file")
    assert res.status_code == 400
    assert "outside repository bounds" in res.json()["detail"].lower()

def test_recon_rejects_oversized_file_reads(test_client, session_with_repo, tmp_path):
    session_id, repo_handle = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")

    repo_dir = Path(AppSessionService.get_path_from_handle(repo_handle))
    big_file = repo_dir / "large.py"
    big_file.write_text("x" * 500001, encoding="utf-8")

    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    large_handle = next(item["handle"] for item in res.json() if item["name"] == "large.py")

    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/read/{large_handle}")
    assert res.status_code == 400
    assert "too large" in res.json()["detail"].lower()

def test_draft_validation_rejects_untrusted_allowed_paths(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")

    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    file_handle = res.json()[0]["handle"]
    test_client.get(f"/ops/app/sessions/{session_id}/recon/read/{file_handle}")

    for allowed_path in ("../secret.py", "*", "not-read.py"):
        res = test_client.post(
            f"/ops/app/sessions/{session_id}/drafts",
            json={
                "acceptance_criteria": "Bound to recon",
                "allowed_paths": [allowed_path],
            },
        )
        assert res.status_code == 403
        assert "allowed_paths" in res.json()["detail"]

def test_recon_with_invalid_bound_repo_handle_is_rejected(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    res = test_client.post("/ops/app/sessions", json={})
    session_id = res.json()["id"]
    session = AppSessionService.get_session(session_id)
    session["repo_id"] = "invalid-handle"
    AppSessionService._save_session(session_id, session)

    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    assert res.status_code == 400
    assert "invalid repo handle" in res.json()["detail"].lower()

def test_draft_validation_requires_acceptance_criteria_payload(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")

    res = test_client.get(f"/ops/app/sessions/{session_id}/recon/list")
    file_handle = res.json()[0]["handle"]
    test_client.get(f"/ops/app/sessions/{session_id}/recon/read/{file_handle}")

    res = test_client.post(f"/ops/app/sessions/{session_id}/drafts", json={"allowed_paths": ["app.py"]})
    assert res.status_code == 422
    assert res.json()["detail"] == "Invalid request payload."

def test_context_request_routes_fail_honestly_for_missing_session_and_request(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    res = test_client.get("/ops/app/sessions/missing-session/context-requests")
    assert res.status_code == 404
    assert res.json()["detail"] == "Session not found"

    create = test_client.post("/ops/app/sessions", json={})
    session_id = create.json()["id"]

    res = test_client.post(
        f"/ops/app/sessions/{session_id}/context-requests/missing-request/resolve",
        json={"evidence": "done"},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Request not found"

def test_context_request_active_and_history_views_are_coherent(test_client, session_with_repo):
    session_id, _ = session_with_repo
    app.dependency_overrides[verify_token] = _auth("operator")

    pending = ContextRequestService.create_request(session_id, "pending")
    resolved = ContextRequestService.create_request(session_id, "resolved")
    cancelled = ContextRequestService.create_request(session_id, "cancelled")

    assert ContextRequestService.resolve_request(session_id, resolved["id"], "done")
    assert ContextRequestService.cancel_request(session_id, cancelled["id"], "stop")
    ContextRequestService.archive_resolved_requests(session_id)

    active_ids = {item["id"] for item in ContextRequestService.get_active_requests(session_id)}
    history_statuses = {item["id"]: item["status"] for item in ContextRequestService.get_request_history(session_id)}

    assert pending["id"] in active_ids
    assert resolved["id"] not in active_ids
    assert cancelled["id"] not in active_ids
    assert history_statuses[resolved["id"]] == "archived"
    assert history_statuses[cancelled["id"]] == "cancelled"

    res = test_client.post(
        f"/ops/app/sessions/{session_id}/context-requests/missing-request/cancel",
        json={"reason": "stop"},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Request not found"
