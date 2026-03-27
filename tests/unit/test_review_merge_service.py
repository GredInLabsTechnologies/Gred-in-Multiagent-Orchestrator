import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.gimo_server.models.core import OpsRun
from tools.gimo_server.services.lifecycle_errors import LifecycleProofError
from tools.gimo_server.services.review_merge_service import ReviewMergeService


@pytest.fixture
def mock_run():
    return OpsRun(
        id="r1",
        approved_id="a1",
        status="done",
        commit_base="base123",
        validated_task_spec={
            "workspace_path": "/tmp/workspace",
            "base_commit": "base123",
        },
        log=[
            {"ts": "2026-03-26T00:00:00Z", "level": "INFO", "msg": "tests_output_tail=PASSED"},
            {"ts": "2026-03-26T00:00:01Z", "level": "INFO", "msg": "lint_output_tail=CLEAN"},
        ],
    )


def _settings(repo_root="/repo", ephemeral_root="/tmp", worktree_root="/worktrees"):
    return MagicMock(
        repo_root_dir=repo_root,
        ephemeral_repos_dir=ephemeral_root,
        worktrees_dir=worktree_root,
    )


def test_build_review_bundle_success(mock_run):
    settings = _settings()
    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.review_merge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True), \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit", side_effect=["head456", "base123"]), \
         patch("tools.gimo_server.services.git_service.GitService.get_changed_files", return_value=["file1.py"]), \
         patch("tools.gimo_server.services.git_service.GitService.get_diff_text", return_value="diff content"):
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
    settings = _settings()
    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.review_merge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True), \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit", side_effect=["head456", "drifted789"]), \
         patch("tools.gimo_server.services.git_service.GitService.get_changed_files", return_value=["file1.py"]), \
         patch("tools.gimo_server.services.git_service.GitService.get_diff_text", return_value="diff content"):
        bundle = ReviewMergeService.build_review_bundle("r1")

    assert bundle.drift_detected
    assert bundle.source_repo_head == "drifted789"


def test_get_merge_preview_success(mock_run):
    settings = _settings()
    with patch("tools.gimo_server.services.review_merge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit", return_value="base123"):
        preview = ReviewMergeService.get_merge_preview("r1")

    assert not preview.drift_detected
    assert preview.manual_merge_required
    assert preview.can_merge


def test_get_merge_preview_drift(mock_run):
    settings = _settings()
    with patch("tools.gimo_server.services.review_merge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit", return_value="drifted789"):
        preview = ReviewMergeService.get_merge_preview("r1")

    assert preview.drift_detected
    assert not preview.can_merge
    assert preview.manual_merge_required
    assert preview.reason == "Source repo has drifted from expected base"


def test_fail_closed_on_missing_base(mock_run):
    mock_run.commit_base = None
    mock_run.validated_task_spec = {}
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with pytest.raises(RuntimeError, match="Base commit for run r1 cannot be proven"):
            ReviewMergeService.get_merge_preview("r1")


def test_build_review_bundle_uses_workspace_evidence_origin(mock_run):
    settings = _settings()
    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.review_merge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True), \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit", side_effect=["head456", "base123"]), \
         patch("tools.gimo_server.services.git_service.GitService.get_changed_files", return_value=["file1.py"]) as mock_changed, \
         patch("tools.gimo_server.services.git_service.GitService.get_diff_text", return_value="diff content") as mock_diff:
        bundle = ReviewMergeService.build_review_bundle("r1")

    assert bundle.changed_files == ["file1.py"]
    mock_changed.assert_called_once_with(Path("C:/tmp/workspace"), base="base123")
    mock_diff.assert_called_once_with(Path("C:/tmp/workspace"), base="base123")


def test_build_review_bundle_fails_on_workspace_outside_canonical_roots(mock_run):
    settings = _settings(ephemeral_root="/safe/ephemeral", worktree_root="/safe/worktrees")
    mock_run.validated_task_spec["workspace_path"] = "/unsafe/workspace"

    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with pytest.raises(LifecycleProofError, match="outside canonical workspace roots"):
            ReviewMergeService.build_review_bundle("r1")
