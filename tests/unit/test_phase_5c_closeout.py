import pytest
import hashlib
import os
import json
from pathlib import Path
from tools.gimo_server.services.draft_validation_service import DraftValidationService
from tools.gimo_server.services.run_worker import RunWorker
from tools.gimo_server.models.core import OpsApproved
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_session():
    return {
        "id": "sess_123",
        "repo_id": "repo_123",
        "read_proofs": [
            {
                "proof_id": "p1",
                "artifact_handle": "h1",
                "kind": "read",
                "evidence_hash": "hash_file1",
                "base_commit": "c1"
            },
            {
                "proof_id": "p2",
                "artifact_handle": "h2",
                "kind": "read",
                "evidence_hash": "hash_file2",
                "base_commit": "c1"
            }
        ],
        "recon_handles": {
            "h1": "file1.py",
            "h2": "file2.py"
        }
    }

def test_evidence_hash_is_deterministic_and_content_based(mock_session):
    payload = {"acceptance_criteria": "done", "allowed_paths": ["file1.py"]}
    
    with patch("tools.gimo_server.services.app_session_service.AppSessionService.get_session", return_value=mock_session):
        with patch("tools.gimo_server.services.app_session_service.AppSessionService._save_session"):
            res1 = DraftValidationService.validate_draft("sess_123", payload)
            spec1 = res1["validated_task_spec"]
            
            # Change proof_id but keep content fields the same
            mock_session["read_proofs"][0]["proof_id"] = "p1_new"
            res2 = DraftValidationService.validate_draft("sess_123", payload)
            spec2 = res2["validated_task_spec"]
            
            # Hash should be the same because content fields haven't changed
            assert spec1["evidence_hash"] == spec2["evidence_hash"]
            
            # Change evidence_hash (content) -> hash should change
            mock_session["read_proofs"][0]["evidence_hash"] = "hash_file1_modified"
            res3 = DraftValidationService.validate_draft("sess_123", payload)
            spec3 = res3["validated_task_spec"]
            assert spec1["evidence_hash"] != spec3["evidence_hash"]

def test_evidence_hash_stable_ordering(mock_session):
    payload = {"acceptance_criteria": "done"}
    with patch("tools.gimo_server.services.app_session_service.AppSessionService.get_session", return_value=mock_session):
        with patch("tools.gimo_server.services.app_session_service.AppSessionService._save_session"):
            res1 = DraftValidationService.validate_draft("sess_123", payload)
            h1 = res1["validated_task_spec"]["evidence_hash"]
            
            # Reverse order of proofs in session
            mock_session["read_proofs"] = mock_session["read_proofs"][::-1]
            res2 = DraftValidationService.validate_draft("sess_123", payload)
            h2 = res2["validated_task_spec"]["evidence_hash"]
            
            # Should be identical due to internal sorting
            assert h1 == h2

def test_worker_context_adjacency_enrichment(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text("def main(): pass")
    (repo_root / "src" / "utils.py").write_text("def util(): pass")
    (repo_root / "README.md").write_text("docs")
    
    worker = RunWorker()
    # seeds with main.py, should pull utils.py due to adjacency
    context = worker._build_worker_context(
        task={"allowed_paths": ["src/main.py"]},
        repo_root=repo_root,
        max_files=5
    )
    
    paths = [c["path"] for c in context]
    assert "src/main.py" in paths
    # It should pull utils.py because it's in the same directory
    assert "src/utils.py" in paths
    assert "README.md" not in paths # Different directory

def test_worker_context_strict_max_files_limit(tmp_path):
    repo_root = tmp_path / "repo_limit"
    repo_root.mkdir()
    for i in range(15):
        (repo_root / f"file{i}.py").write_text("pass")
        
    worker = RunWorker()
    # Try to request 12 files
    context = worker._build_worker_context(
        task={"allowed_paths": [f"file{i}.py" for i in range(15)]},
        repo_root=repo_root,
        max_files=12
    )
    
    # Strictly capped at 10
    assert len(context) == 10

@pytest.mark.asyncio
async def test_legacy_paths_are_blocked():
    worker = RunWorker()
    assert worker._extract_target_path("foo") is None
    assert await worker._execute_file_task() is False
    # These should just pass/no-op as they are now empty
    await worker._process_task()
    await worker._execute_structured_plan()
    await worker._handle_legacy_execution()

@pytest.mark.asyncio
async def test_hardened_task_spec_validation(mock_session):
    worker = RunWorker()
    
    # Missing fields
    bad_spec = {"base_commit": "HEAD"}
    valid, err = worker._validate_task_spec(bad_spec)
    assert not valid
    assert "Schema validation failed" in err
    
    # requires_manual_merge must be True
    bad_spec2 = {
        "base_commit": "HEAD",
        "repo_handle": "h1",
        "allowed_paths": ["f1.py"],
        "acceptance_criteria": "done",
        "evidence_hash": "abc",
        "context_pack_id": "cp1",
        "worker_model": "m1",
        "requires_manual_merge": False
    }
    valid, err = worker._validate_task_spec(bad_spec2)
    assert not valid
    assert "requires_manual_merge must be True" in err

def test_missing_evidence_field_fails_closed(mock_session):
    # Remove a required field from one proof
    del mock_session["read_proofs"][0]["evidence_hash"]
    payload = {"acceptance_criteria": "done"}
    
    with patch("tools.gimo_server.services.app_session_service.AppSessionService.get_session", return_value=mock_session):
        with pytest.raises(ValueError, match="Field 'evidence_hash' is missing or empty"):
            DraftValidationService.validate_draft("sess_123", payload)

def test_whitespace_evidence_field_fails_closed(mock_session):
    # Set a required field to whitespace
    mock_session["read_proofs"][0]["artifact_handle"] = "  "
    payload = {"acceptance_criteria": "done"}
    
    with patch("tools.gimo_server.services.app_session_service.AppSessionService.get_session", return_value=mock_session):
        with pytest.raises(ValueError, match="Field 'artifact_handle' is missing or empty"):
            DraftValidationService.validate_draft("sess_123", payload)

def test_empty_evidence_set_fails_closed(mock_session):
    mock_session["read_proofs"] = []
    payload = {"acceptance_criteria": "done"}
    
    with patch("tools.gimo_server.services.app_session_service.AppSessionService.get_session", return_value=mock_session):
        with pytest.raises(ValueError, match="No reconnaissance evidence recorded"):
            DraftValidationService.validate_draft("sess_123", payload)

def test_deterministic_allowed_paths_fallback(mock_session):
    # Case where allowed_paths is NOT provided in payload
    payload = {"acceptance_criteria": "done"}
    
    with patch("tools.gimo_server.services.app_session_service.AppSessionService.get_session", return_value=mock_session):
        with patch("tools.gimo_server.services.app_session_service.AppSessionService._save_session"):
            res = DraftValidationService.validate_draft("sess_123", payload)
            paths = res["validated_task_spec"]["allowed_paths"]
            
            # Since mock_session has h1 (file1.py) and h2 (file2.py), and kind is 'read'
            # Stable sort key (artifact_handle, kind) means h1:read, h2:read is the order
            assert paths == ["file1.py", "file2.py"]
            
            # Change discovery order in read_proofs list
            mock_session["read_proofs"] = mock_session["read_proofs"][::-1]
            res2 = DraftValidationService.validate_draft("sess_123", payload)
            paths2 = res2["validated_task_spec"]["allowed_paths"]
            
            # Should STILL be the same due to internal sorting before extraction
            assert paths == paths2
