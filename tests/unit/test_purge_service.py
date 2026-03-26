import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from tools.gimo_server.services.purge_service import PurgeService
from tools.gimo_server.models.core import OpsRun, PurgeReceipt

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
            "base_commit": "base123"
        },
        model_tier=2,
        risk_score=0.1
    )

def test_purge_removes_reconstructive_state(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.ops_service.OpsService._run_events_path", return_value=Path("events.jsonl")):
            with patch("tools.gimo_server.services.ops_service.OpsService._run_log_path", return_value=Path("logs.jsonl")):
                with patch("tools.gimo_server.services.ops_service.OpsService._run_path", return_value=Path("run.json")):
                    with patch("pathlib.Path.exists", return_value=True):
                        # Use autospec=True to ensure self is passed correctly
                        with patch("pathlib.Path.resolve", autospec=True, side_effect=lambda self: self):
                            with patch("pathlib.Path.unlink") as mock_unlink:
                                with patch("tools.gimo_server.services.git_service.GitService.remove_worktree") as mock_git_rm:
                                    with patch("tools.gimo_server.services.purge_service.shutil.rmtree") as mock_rmtree:
                                        with patch("pathlib.Path.write_text") as mock_write:
                                            with patch("tools.gimo_server.services.purge_service.PurgeService._persist_receipt") as mock_persist:
                                                receipt = PurgeService.purge_run("r_test_purge")
                                                
                                                assert receipt.success
                                                assert "workspace" in receipt.removed_categories
                                                assert "events" in receipt.removed_categories
                                                assert "logs" in receipt.removed_categories
                                                
                                                # Verify unlinks (events, logs)
                                                assert mock_unlink.call_count >= 2
                                                mock_git_rm.assert_called_once()

def test_minimal_terminal_metadata_only(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.ops_service.OpsService._run_events_path", return_value=Path("events.jsonl")):
            with patch("tools.gimo_server.services.ops_service.OpsService._run_log_path", return_value=Path("logs.jsonl")):
                with patch("tools.gimo_server.services.ops_service.OpsService._run_path", return_value=Path("run.json")):
                    with patch("pathlib.Path.exists", return_value=False):
                        with patch("pathlib.Path.resolve", autospec=True, side_effect=lambda self: self):
                            with patch("pathlib.Path.write_text") as mock_write:
                                 with patch("tools.gimo_server.services.purge_service.PurgeService._persist_receipt"):
                                    PurgeService.purge_run("r_test_purge")
                                    
                                    # Filter writes to run.json
                                    for call in mock_write.call_args_list:
                                        try:
                                            saved_data = json.loads(call.args[0])
                                            if "id" in saved_data:
                                                assert "id" in saved_data
                                                assert "status" in saved_data
                                                assert "validated_task_spec" not in saved_data
                                                assert "log" not in saved_data
                                                return
                                        except:
                                            continue
                                    pytest.fail("Write text not called with run data")

def test_purge_fails_on_repo_root(mock_run):
    settings_mock = MagicMock()
    # Use consistent paths that would resolve differently if not mocked, 
    # but we will mock them to be equal
    settings_mock.repo_root_dir = "/repo"
    mock_run.validated_task_spec["workspace_path"] = "/workspace"
    
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.purge_service.get_settings", return_value=settings_mock):
            # We need to control equality. Path equality usually compares resolved paths.
            # Easiest way: just mock the equality operator of the Path class or use same strings and let real Path handle it
            with patch("pathlib.Path.exists", return_value=True):
                # By using same strings, real Path will resolve them to same thing
                mock_run.validated_task_spec["workspace_path"] = "/repo"
                with pytest.raises(RuntimeError) as excinfo:
                    PurgeService.purge_run("r_test_purge")
                assert "matches repo_root" in str(excinfo.value)

def test_purge_fails_closed_on_unlink_error(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.ops_service.OpsService._run_events_path", return_value=Path("events.jsonl")):
            mock_run.validated_task_spec["workspace_path"] = None # Skip workspace
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.unlink", side_effect=IOError("Permission denied")):
                    with pytest.raises(RuntimeError) as excinfo:
                        PurgeService.purge_run("r_test_purge")
                    assert "Failed to unlink events" in str(excinfo.value)

def test_purge_receipt_behavioral(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.ops_service.OpsService._run_events_path", return_value=Path("events.jsonl")):
            with patch("tools.gimo_server.services.ops_service.OpsService._run_log_path", return_value=Path("logs.jsonl")):
                with patch("tools.gimo_server.services.ops_service.OpsService._run_path", return_value=Path("run.json")):
                    with patch("pathlib.Path.exists", return_value=False):
                        with patch("pathlib.Path.write_text"):
                             with patch("tools.gimo_server.services.purge_service.PurgeService._persist_receipt") as mock_persist:
                                receipt = PurgeService.purge_run("r_test_purge")
                                assert receipt.success
                                assert receipt.run_id == "r_test_purge"
                                assert isinstance(receipt.retained_metadata_hash, str)
                                mock_persist.assert_called_once()
