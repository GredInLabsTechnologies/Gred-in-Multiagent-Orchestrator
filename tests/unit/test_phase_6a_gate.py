import pytest
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


def test_invariant_review_bundle_contains_changed_files(mock_run):
    settings = _settings()
    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.review_merge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True), \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit", side_effect=["h", "b"]), \
         patch("tools.gimo_server.services.git_service.GitService.get_changed_files", return_value=["f1.py", "f2.py"]), \
         patch("tools.gimo_server.services.git_service.GitService.get_diff_text", return_value="diff"):
        bundle = ReviewMergeService.build_review_bundle("r1")

    assert len(bundle.changed_files) == 2
    assert "f1.py" in bundle.changed_files


def test_invariant_review_bundle_contains_diff_or_diff_summary(mock_run):
    settings = _settings()
    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.review_merge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True), \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit", side_effect=["h", "b"]), \
         patch("tools.gimo_server.services.git_service.GitService.get_changed_files", return_value=[]), \
         patch("tools.gimo_server.services.git_service.GitService.get_diff_text", return_value="ACTUAL_DIFF_CONTENT"):
        bundle = ReviewMergeService.build_review_bundle("r1")

    assert bundle.diff_summary == "ACTUAL_DIFF_CONTENT"


def test_invariant_review_bundle_carries_available_logs_and_test_evidence(mock_run):
    settings = _settings()
    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.review_merge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True), \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit", side_effect=["h", "b"]), \
         patch("tools.gimo_server.services.git_service.GitService.get_changed_files", return_value=[]), \
         patch("tools.gimo_server.services.git_service.GitService.get_diff_text", return_value=""):
        bundle = ReviewMergeService.build_review_bundle("r1")

    assert bundle.test_evidence == "PASSED"
    assert bundle.lint_evidence == "CLEAN"
    assert len(bundle.logs) == 2


def test_invariant_merge_preview_detects_base_drift(mock_run):
    settings = _settings()
    with patch("tools.gimo_server.services.review_merge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", return_value="base123"):
            preview = ReviewMergeService.get_merge_preview("r1")
            assert not preview.drift_detected

        with patch("tools.gimo_server.services.git_service.GitService.get_head_commit", return_value="different456"):
            preview = ReviewMergeService.get_merge_preview("r1")
            assert preview.drift_detected


def test_invariant_manual_merge_only(mock_run):
    settings = _settings()
    with patch("tools.gimo_server.services.review_merge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit", return_value="base123"):
        preview = ReviewMergeService.get_merge_preview("r1")

    assert preview.manual_merge_required is True


def test_invariant_source_repo_untouched_until_explicit_final_merge():
    with patch("tools.gimo_server.services.git_service.GitService.perform_merge") as mock_merge, \
         patch("tools.gimo_server.services.git_service.GitService.commit_all") as mock_commit:
        assert mock_merge.call_count == 0
        assert mock_commit.call_count == 0


def test_invariant_workspace_must_stay_inside_canonical_roots(mock_run):
    settings = _settings(ephemeral_root="/tmp", worktree_root="/worktrees")
    mock_run.validated_task_spec["workspace_path"] = "/unsafe/workspace"

    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with pytest.raises(LifecycleProofError, match="outside canonical workspace roots"):
            ReviewMergeService.build_review_bundle("r1")
