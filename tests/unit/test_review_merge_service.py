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

def test_build_review_bundle_success(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("pathlib.Path.exists", return_value=True):
            # First call: workspace head. Second call: source repo head.
            with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", side_effect=["head456", "base123"]):
                with patch("tools.gimo_server.services.git_service.GitService.get_changed_files", return_value=["file1.py"]):
                    with patch("tools.gimo_server.services.git_service.GitService.get_diff_text", return_value="diff content"):
                        bundle = ReviewMergeService.build_review_bundle("r1")
                        
                        assert bundle.run_id == "r1"
                        assert bundle.base_commit == "base123"
                        assert bundle.head_commit == "head456"
                        assert bundle.changed_files == ["file1.py"]
                        assert bundle.diff_summary == "diff content"
                        assert bundle.test_evidence == "PASSED"
                        assert bundle.lint_evidence == "CLEAN"
                        assert not bundle.drift_detected

def test_build_review_bundle_drift_detected(mock_run):
    # actual source head is different from base_commit
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("pathlib.Path.exists", return_value=True):
            # First call: workspace head. Second call: source repo head (drifted).
            with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", side_effect=["head456", "drifted789"]):
                with patch("tools.gimo_server.services.git_service.GitService.get_changed_files", return_value=["file1.py"]):
                    with patch("tools.gimo_server.services.git_service.GitService.get_diff_text", return_value="diff content"):
                        bundle = ReviewMergeService.build_review_bundle("r1")
                        
                        assert bundle.drift_detected
                        assert bundle.source_repo_head == "drifted789"

def test_get_merge_preview_success(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", return_value="base123"):
            preview = ReviewMergeService.get_merge_preview("r1")
            
            assert not preview.drift_detected
            assert preview.manual_merge_required
            assert preview.can_merge

def test_get_merge_preview_drift(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", return_value="drifted789"):
            preview = ReviewMergeService.get_merge_preview("r1")
            
            assert preview.drift_detected
            assert not preview.can_merge
            assert preview.manual_merge_required

def test_fail_closed_on_missing_base(mock_run):
    mock_run.commit_base = None
    mock_run.validated_task_spec = {}
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        # build_review_bundle also fails closed
        with pytest.raises(RuntimeError, match="Base commit for run r1 cannot be proven"):
            ReviewMergeService.get_merge_preview("r1")
