import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.purge_service import PurgeService
from tools.gimo_server.models.core import OpsRun, PurgeReceipt

def create_mock_run(run_id):
    return OpsRun(
        id=run_id,
        approved_id="a1",
        status="done",
        commit_base="base123",
        commit_after="after456",
        validated_task_spec={},
        model_tier=2,
        risk_score=0.1
    )

def test_invariant_purge_receipt_persisted(tmp_path):
    # Behavioral proof: Purge receipt must be physically persisted in OPS_DIR
    mock_run = create_mock_run("r_receipt_test")
    temp_ops_dir = tmp_path / "ops"
    temp_ops_dir.mkdir()
    
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.ops_service.OpsService._run_events_path", return_value=temp_ops_dir / "events.jsonl"):
            with patch("tools.gimo_server.services.ops_service.OpsService._run_log_path", return_value=temp_ops_dir / "logs.jsonl"):
                with patch("tools.gimo_server.services.ops_service.OpsService._run_path", return_value=temp_ops_dir / "run.json"):
                    with patch("tools.gimo_server.services.ops_service.OpsService.OPS_DIR", temp_ops_dir):
                        # Ensure run.json exists so write_text doesn't fail
                        (temp_ops_dir / "run.json").write_text("{}", encoding="utf-8")
                        
                        receipt = PurgeService.purge_run("r_receipt_test")
                        assert receipt.success
                        
                        # Verify real receipt file existence
                        receipt_path = temp_ops_dir / "purge_receipts" / f"purge_{receipt.run_id}.json"
                        assert receipt_path.exists(), f"Purge receipt not found at {receipt_path}"
                        
                        # Verify content integrity
                        content = json.loads(receipt_path.read_text(encoding="utf-8"))
                        assert content["run_id"] == "r_receipt_test"
                        assert content["success"] is True
                        assert "retained_metadata_hash" in content
                        assert "removed_categories" in content

def test_invariant_minimal_terminal_metadata_only():
    # Proves reconstructive fields are removed and terminal metadata is minimal
    mock_run = create_mock_run("r_meta")
    mock_run.validated_task_spec = {"secret": "reconstructive"}
    mock_run.log = [{"msg": "secret"}]
    
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.ops_service.OpsService._run_path", return_value=Path("run.json")):
            with patch("pathlib.Path.exists", return_value=False):
                 with patch("pathlib.Path.write_text") as mock_write:
                     with patch("tools.gimo_server.services.purge_service.PurgeService._persist_receipt"):
                        PurgeService.purge_run("r_meta")
                        
                        # Inspect the data written to disk
                        for call in mock_write.call_args_list:
                            try:
                                saved = json.loads(call.args[0])
                                if "id" in saved and saved["id"] == "r_meta":
                                    assert "status" in saved
                                    assert "validated_task_spec" not in saved
                                    assert "log" not in saved
                                    return
                            except:
                                continue
                        pytest.fail("Minimal metadata was not saved")

def test_invariant_purge_fails_closed_on_partial_cleanup():
    # Mandatory for Phase 6B: if one step fails, the whole purge raises RuntimeError
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", side_effect=Exception("Database down")):
        with pytest.raises(RuntimeError) as excinfo:
            PurgeService.purge_run("r1")
        assert "Purge failed" in str(excinfo.value)

def test_invariant_workspace_equals_repo_root_fails_closed():
    mock_run = create_mock_run("r_root")
    mock_run.validated_task_spec = {"workspace_path": "/repo"}
    
    settings_mock = MagicMock()
    settings_mock.repo_root_dir = "/repo"

    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with patch("tools.gimo_server.services.purge_service.get_settings", return_value=settings_mock):
            with patch("pathlib.Path.exists", return_value=True):
                with pytest.raises(RuntimeError) as excinfo:
                    PurgeService.purge_run("r_root")
                assert "matches repo_root" in str(excinfo.value)

def test_invariant_no_phase_7_started():
    # Check for forbidden files that belong to Phase 7
    root = Path(__file__).parent.parent.parent
    phase_7_files = list(root.glob("tools/gimo_server/services/consolidation_service.py"))
    assert len(phase_7_files) == 0, "Phase 7 consolidation service detected"
    
    # Check for TUI work in routers (Phase 7 boundary)
    router_path = root / "tools/gimo_server/routers"
    if router_path.exists():
        tui_routers = list(router_path.glob("tui*.py"))
        assert len(tui_routers) == 0, "Phase 7 TUI routers detected"
