import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.gimo_server.models.core import OpsRun, PurgeReceipt
from tools.gimo_server.services.lifecycle_errors import LifecycleProofError, PurgeExecutionError
from tools.gimo_server.services.ops import OpsService
from tools.gimo_server.services.purge_service import PurgeService


@pytest.fixture
def mock_run():
    return OpsRun(
        id="r_test_purge",
        approved_id="a1",
        status="done",
        commit_base="base123",
        commit_after="after456",
        validated_task_spec={
            "workspace_path": "c:/tmp/test_workspace",
            "base_commit": "base123",
        },
        model_tier=2,
        risk_score=0.1,
    )


def _settings(repo_root="c:/repo", worktree_root="c:/worktrees", ephemeral_root="c:/tmp"):
    return MagicMock(
        repo_root_dir=Path(repo_root),
        worktrees_dir=Path(worktree_root),
        ephemeral_repos_dir=Path(ephemeral_root),
        repo_mirrors_dir=Path("c:/mirrors"),
        purge_quarantine_dir=Path("c:/quarantine"),
    )


def test_purge_removes_reconstructive_state(mock_run):
    settings = _settings()
    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.purge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops.OpsService.get_run", return_value=mock_run), \
         patch("tools.gimo_server.services.ops.OpsService._run_events_path", return_value=Path("events.jsonl")), \
         patch("tools.gimo_server.services.ops.OpsService._run_log_path", return_value=Path("logs.jsonl")), \
         patch("tools.gimo_server.services.ops.OpsService._run_path", return_value=Path("run.json")), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True), \
         patch("pathlib.Path.resolve", autospec=True, side_effect=lambda self: self), \
         patch("pathlib.Path.unlink") as mock_unlink, \
         patch("tools.gimo_server.services.purge_service.EphemeralRepoService.destroy_workspace") as mock_destroy, \
         patch("tools.gimo_server.services.git_service.GitService.remove_worktree") as mock_git_rm, \
         patch("pathlib.Path.write_text"), \
         patch("tools.gimo_server.services.purge_service.PurgeService._persist_receipt"):
        receipt = PurgeService.purge_run("r_test_purge")

    assert receipt.success
    assert "workspace" in receipt.removed_categories
    assert "events" in receipt.removed_categories
    assert "logs" in receipt.removed_categories
    assert mock_unlink.call_count >= 2
    mock_destroy.assert_called_once_with(Path("c:/tmp/test_workspace"))
    mock_git_rm.assert_not_called()


def test_minimal_terminal_metadata_only(mock_run):
    settings = _settings()
    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.purge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops.OpsService.get_run", return_value=mock_run), \
         patch("tools.gimo_server.services.ops.OpsService._run_events_path", return_value=Path("events.jsonl")), \
         patch("tools.gimo_server.services.ops.OpsService._run_log_path", return_value=Path("logs.jsonl")), \
         patch("tools.gimo_server.services.ops.OpsService._run_path", return_value=Path("run.json")), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("pathlib.Path.is_dir", return_value=True), \
         patch("pathlib.Path.resolve", autospec=True, side_effect=lambda self: self), \
         patch("pathlib.Path.write_text") as mock_write, \
         patch("tools.gimo_server.services.purge_service.PurgeService._persist_receipt"):
        PurgeService.purge_run("r_test_purge")

    for call in mock_write.call_args_list:
        try:
            saved_data = json.loads(call.args[0])
        except Exception:
            continue
        if saved_data.get("id") == "r_test_purge":
            assert "id" in saved_data
            assert "status" in saved_data
            assert "validated_task_spec" not in saved_data
            assert "log" not in saved_data
            return
    pytest.fail("Write text not called with run terminal metadata")


def test_purge_fails_on_repo_root(mock_run):
    settings = _settings(repo_root="/repo", ephemeral_root="/repo")
    mock_run.validated_task_spec["workspace_path"] = "/repo"

    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.purge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops.OpsService.get_run", return_value=mock_run), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True):
        with pytest.raises(LifecycleProofError, match="resolves to repo_root"):
            PurgeService.purge_run("r_test_purge")


def test_purge_fails_closed_on_unlink_error(mock_run):
    settings = _settings()
    mock_run.validated_task_spec["workspace_path"] = None
    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.purge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops.OpsService.get_run", return_value=mock_run), \
         patch("tools.gimo_server.services.ops.OpsService._run_events_path", return_value=Path("events.jsonl")), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.unlink", side_effect=IOError("Permission denied")):
        with pytest.raises(PurgeExecutionError, match="Failed to unlink events"):
            PurgeService.purge_run("r_test_purge")


def test_purge_receipt_behavioral(mock_run, tmp_path):
    temp_ops_dir = tmp_path / "ops"
    temp_ops_dir.mkdir()
    settings = _settings(
        repo_root=str(tmp_path / "repo"),
        worktree_root=str(tmp_path / "worktrees"),
        ephemeral_root="c:/tmp",
    )

    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.purge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops.OpsService.get_run", return_value=mock_run), \
         patch("tools.gimo_server.services.ops.OpsService._run_events_path", return_value=temp_ops_dir / "events.jsonl"), \
         patch("tools.gimo_server.services.ops.OpsService._run_log_path", return_value=temp_ops_dir / "logs.jsonl"), \
         patch("tools.gimo_server.services.ops.OpsService._run_path", return_value=temp_ops_dir / "run.json"), \
         patch("tools.gimo_server.services.ops.OpsService.OPS_DIR", temp_ops_dir):
        (temp_ops_dir / "run.json").write_text("{}", encoding="utf-8")
        receipt = PurgeService.purge_run("r_test_purge")

    assert receipt.success
    assert receipt.run_id == "r_test_purge"
    receipt_file = temp_ops_dir / "purge_receipts" / f"purge_{receipt.run_id}.json"
    assert receipt_file.exists()
    saved_receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    assert saved_receipt["run_id"] == "r_test_purge"
    assert saved_receipt["success"] is True
    assert "retained_metadata_hash" in saved_receipt
    assert isinstance(saved_receipt["removed_categories"], list)


def test_purge_fails_on_workspace_outside_canonical_roots(mock_run):
    settings = _settings(ephemeral_root="c:/ephemeral")
    mock_run.validated_task_spec["workspace_path"] = "c:/unsafe/workspace"

    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops.OpsService.get_run", return_value=mock_run):
        with pytest.raises(LifecycleProofError, match="outside canonical workspace roots"):
            PurgeService.purge_run("r_test_purge")


def test_discard_run_cancels_non_terminal_run_before_purge(mock_run):
    mock_run.status = "running"
    receipt = PurgeReceipt(
        run_id="r_test_purge",
        removed_categories=["workspace"],
        retained_metadata_hash="hash",
        success=True,
    )

    with patch("tools.gimo_server.services.ops._run.RunMixin.get_run", return_value=mock_run), \
         patch("tools.gimo_server.services.ops._run.RunMixin.update_run_status") as mock_status, \
         patch("tools.gimo_server.services.purge_service.PurgeService.purge_run", return_value=receipt) as mock_purge:
        result = OpsService.discard_run("r_test_purge")

    assert result == receipt
    mock_status.assert_called_once_with("r_test_purge", "cancelled", msg="Discarded by user")
    mock_purge.assert_called_once_with("r_test_purge")
