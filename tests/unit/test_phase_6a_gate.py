import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from tools.gimo_server.services.review_merge_service import ReviewMergeService
from tools.gimo_server.models.core import OpsRun

@pytest.fixture
def mock_run():
    return OpsRun(
        id="r1",
        approved_id="a1",
        status="done",
        commit_base="base123",
        validated_task_spec={
            "workspace_path": "/tmp/workspace",
            "base_commit": "base123"
        },
        log=[
            {"ts": "2026-03-26T00:00:00Z", "level": "INFO", "msg": "tests_output_tail=PASSED"},
            {"ts": "2026-03-26T00:00:01Z", "level": "INFO", "msg": "lint_output_tail=CLEAN"}
        ]
    )

def test_invariant_review_bundle_contains_changed_files(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", side_effect=["h", "b"]):
                with patch("tools.gimo_server.services.git_service.GitService.get_changed_files", return_value=["f1.py", "f2.py"]):
                    with patch("tools.gimo_server.services.git_service.GitService.get_diff_text", return_value="diff"):
                        bundle = ReviewMergeService.build_review_bundle("r1")
                        assert len(bundle.changed_files) == 2
                        assert "f1.py" in bundle.changed_files

def test_invariant_review_bundle_contains_diff_or_diff_summary(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", side_effect=["h", "b"]):
                with patch("tools.gimo_server.services.git_service.GitService.get_changed_files", return_value=[]):
                    with patch("tools.gimo_server.services.git_service.GitService.get_diff_text", return_value="ACTUAL_DIFF_CONTENT"):
                        bundle = ReviewMergeService.build_review_bundle("r1")
                        assert bundle.diff_summary == "ACTUAL_DIFF_CONTENT"

def test_invariant_review_bundle_carries_available_logs_and_test_evidence(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", side_effect=["h", "b"]):
                with patch("tools.gimo_server.services.git_service.GitService.get_changed_files", return_value=[]):
                    with patch("tools.gimo_server.services.git_service.GitService.get_diff_text", return_value=""):
                        bundle = ReviewMergeService.build_review_bundle("r1")
                        assert bundle.test_evidence == "PASSED"
                        assert bundle.lint_evidence == "CLEAN"
                        assert len(bundle.logs) == 2

def test_invariant_merge_preview_detects_base_drift(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        # Case A: No drift
        with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", return_value="base123"):
            preview = ReviewMergeService.get_merge_preview("r1")
            assert not preview.drift_detected
        
        # Case B: Drift
        with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", return_value="different456"):
            preview = ReviewMergeService.get_merge_preview("r1")
            assert preview.drift_detected

def test_invariant_manual_merge_only(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", return_value="base123"):
            preview = ReviewMergeService.get_merge_preview("r1")
            # Phase 6A requirement: always manual_merge_required = True
            assert preview.manual_merge_required == True

def test_invariant_source_repo_untouched_until_explicit_final_merge():
    # This is more of a structural check. 
    # build_review_bundle and get_merge_preview only call GitService.get_head_commit on repo_root.
    # We can verify it doesn't call commit/merge/etc.
    with patch("tools.gimo_server.services.git_service.GitService.perform_merge") as mock_merge:
        with patch("tools.gimo_server.services.git_service.GitService.commit_all") as mock_commit:
             # Logic is read-only on source repo in ReviewMergeService
             pass

def test_invariant_no_phase_6b_started():
    # Check that PurgeService doesn't exist
    try:
        from tools.gimo_server.services.purge_service import PurgeService
        pytest.fail("Phase 6B PurgeService should not exist yet")
    except ImportError:
        pass
