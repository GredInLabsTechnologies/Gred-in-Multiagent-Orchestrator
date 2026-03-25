import pytest
import json
import hashlib
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
                        with patch("pathlib.Path.unlink") as mock_unlink:
                            with patch("tools.gimo_server.services.git_service.GitService.remove_worktree") as mock_git_rm:
                                with patch("pathlib.Path.write_text") as mock_write:
                                    with patch("tools.gimo_server.services.purge_service.PurgeService._persist_receipt") as mock_persist:
                                        receipt = PurgeService.purge_run("r_test_purge")
                                        
                                        assert receipt.success
                                        assert "workspace" in receipt.removed_categories
                                        assert "events" in receipt.removed_categories
                                        assert "logs" in receipt.removed_categories
                                        
                                        # Verify unlinks
                                        assert mock_unlink.call_count >= 2 # events, logs
                                        # Verify git rm
                                        mock_git_rm.assert_called_once()

def test_minimal_terminal_metadata_only(mock_run):
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.ops_service.OpsService._run_events_path", return_value=Path("events.jsonl")):
            with patch("tools.gimo_server.services.ops_service.OpsService._run_log_path", return_value=Path("logs.jsonl")):
                with patch("tools.gimo_server.services.ops_service.OpsService._run_path", return_value=Path("run.json")):
                    with patch("pathlib.Path.exists", return_value=False):
                        with patch("pathlib.Path.write_text") as mock_write:
                             with patch("tools.gimo_server.services.purge_service.PurgeService._persist_receipt"):
                                PurgeService.purge_run("r_test_purge")
                                
                                # The last write should be the minimal metadata
                                # We might have multiple writes if _persist_receipt is also called and not mocked fully
                                # But here we mocked Path.write_text globally
                                
                                # Filter only writes to 'run.json'
                                run_json_writes = [call for call in mock_write.call_args_list if str(call[0][0]) == "run.json"]
                                # Wait, Path objects are passed
                                run_json_writes = [call for call in mock_write.call_args_list if "run.json" in str(call.args[0]) or "run.json" in str(call.args)]
                                
                                if not run_json_writes:
                                    # Fallback check
                                    args, kwargs = mock_write.call_args
                                    saved_data = json.loads(args[0])
                                else:
                                     # Use the first one or however many we found
                                     saved_data = json.loads(run_json_writes[0].args[0])
                                
                                # Check survivor fields
                                assert "id" in saved_data
                                assert "status" in saved_data
                                assert "commit_base" in saved_data
                                assert "commit_after" in saved_data
                                assert "risk_score" in saved_data
                                assert "model_identifier" in saved_data
                                assert "purged" in saved_data
                                
                                # Check reconstructive fields are GONE
                                assert "validated_task_spec" not in saved_data
                                assert "log" not in saved_data
