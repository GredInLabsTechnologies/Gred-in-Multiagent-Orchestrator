import pytest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch
from tools.gimo_server.services.merge_gate_service import MergeGateService
from tools.gimo_server.services.ops_service import OpsService

@pytest.mark.asyncio
async def test_merge_gate_stops_at_awaiting_merge():
    """
    Verifies that for CODE_PATCH, MergeGateService stops after dry-run and 
    transitions to AWAITING_MERGE.
    """
    run_id = str(uuid.uuid4())
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run") as mock_get_run, \
         patch("tools.gimo_server.services.ops_service.OpsService.get_approved") as mock_get_approved, \
         patch("tools.gimo_server.services.ops_service.OpsService.get_draft") as mock_get_draft, \
         patch("tools.gimo_server.services.ops_service.OpsService.update_run_status") as mock_status, \
         patch("tools.gimo_server.services.ops_service.OpsService.append_log"), \
         patch("tools.gimo_server.services.ops_service.OpsService.set_run_stage"), \
         patch("tools.gimo_server.services.ops_service.OpsService.update_run_merge_metadata"), \
         patch("tools.gimo_server.services.git_service.GitService.dry_run_merge") as mock_dry_run, \
         patch("tools.gimo_server.services.git_service.GitService.run_tests") as mock_tests, \
         patch("tools.gimo_server.services.git_service.GitService.run_lint_typecheck") as mock_lint, \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit") as mock_head, \
         patch("tools.gimo_server.services.merge_gate_service.resolve_authoritative_repo_path", return_value=Path("/repo")), \
         patch("tools.gimo_server.services.merge_gate_service.resolve_workspace_path", return_value=Path("/tmp/ws")), \
         patch("tools.gimo_server.services.merge_gate_service.GitService.clean_repo_check", return_value=True), \
         patch("tools.gimo_server.services.merge_gate_service.GitService.fetch_local_ref"):
        
        mock_get_run.return_value = MagicMock(approved_id="app1", risk_score=0.0, policy_decision_id="p1", repo_id="default")
        mock_get_approved.return_value = MagicMock(draft_id="d1")
        mock_get_draft.return_value = MagicMock(
            context={
                "intent_effective": "CODE_PATCH",
                "workspace_path": "/tmp/ws",
                "validated_task_spec": {"repo_handle": "repo_h"},
            }
        )
        
        mock_dry_run.return_value = (True, "Dry run success")
        mock_tests.return_value = (True, "Tests passed")
        mock_lint.return_value = (True, "Lint passed")
        mock_head.return_value = "abc1234"
        
        await MergeGateService.execute_run(run_id)
        
        mock_status.assert_any_call(run_id, "AWAITING_MERGE", msg="Gate passed; awaiting manual merge command.")

@pytest.mark.asyncio
async def test_perform_manual_merge_success():
    """
    Verifies that perform_manual_merge correctly executes the final merge.
    """
    run_id = str(uuid.uuid4())
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run") as mock_get_run, \
         patch("tools.gimo_server.services.ops_service.OpsService.update_run_status") as mock_status, \
         patch("tools.gimo_server.services.ops_service.OpsService.set_run_stage"), \
         patch("tools.gimo_server.services.ops_service.OpsService._load_run_metadata") as mock_load, \
         patch("tools.gimo_server.services.ops_service.OpsService.get_approved") as mock_get_approved, \
         patch("tools.gimo_server.services.ops_service.OpsService.get_draft") as mock_get_draft, \
         patch("tools.gimo_server.services.git_service.GitService.perform_merge") as mock_real_merge, \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit") as mock_head, \
         patch("tools.gimo_server.services.merge_gate_service.resolve_authoritative_repo_path", return_value=Path("/repo")), \
         patch("tools.gimo_server.services.merge_gate_service.resolve_workspace_path", return_value=Path("/tmp/ws")), \
         patch("tools.gimo_server.services.merge_gate_service.GitService.clean_repo_check", return_value=True), \
         patch("tools.gimo_server.services.merge_gate_service.GitService.fetch_local_ref") as mock_fetch:
        
        mock_get_run.return_value = MagicMock(id=run_id, status="AWAITING_MERGE", approved_id="app1", commit_before="abc1234")
        mock_load.return_value = MagicMock(id=run_id, status="AWAITING_MERGE", approved_id="app1", commit_before="abc1234")
        mock_get_approved.return_value = MagicMock(draft_id="d1")
        mock_get_draft.return_value = MagicMock(
            context={"workspace_path": "/tmp/ws", "validated_task_spec": {"repo_handle": "repo_h"}}
        )
        mock_real_merge.return_value = (True, "Real merge success")
        mock_head.return_value = "def5678"
        
        success = await MergeGateService.perform_manual_merge(run_id)
        
        assert success is True
        mock_status.assert_any_call(run_id, "done", msg="manual merge completed successfully")
        mock_fetch.assert_called_once_with(Path("/repo").resolve(), Path("/tmp/ws").resolve(), "def5678")
        mock_real_merge.assert_called_once_with(Path("/repo").resolve(), "FETCH_HEAD", "main")

@pytest.mark.asyncio
async def test_perform_manual_merge_conflict():
    """
    Verifies handling of merge conflicts during manual merge.
    """
    run_id = str(uuid.uuid4())
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run") as mock_get_run, \
         patch("tools.gimo_server.services.ops_service.OpsService.update_run_status") as mock_status, \
         patch("tools.gimo_server.services.ops_service.OpsService.set_run_stage"), \
         patch("tools.gimo_server.services.ops_service.OpsService._load_run_metadata") as mock_load, \
         patch("tools.gimo_server.services.ops_service.OpsService.get_approved") as mock_get_approved, \
         patch("tools.gimo_server.services.ops_service.OpsService.get_draft") as mock_get_draft, \
         patch("tools.gimo_server.services.git_service.GitService.perform_merge") as mock_real_merge, \
         patch("tools.gimo_server.services.git_service.GitService.get_head_commit") as mock_head, \
         patch("tools.gimo_server.services.merge_gate_service.resolve_authoritative_repo_path", return_value=Path("/repo")), \
         patch("tools.gimo_server.services.merge_gate_service.resolve_workspace_path", return_value=Path("/tmp/ws")), \
         patch("tools.gimo_server.services.merge_gate_service.GitService.clean_repo_check", return_value=True), \
         patch("tools.gimo_server.services.merge_gate_service.GitService.fetch_local_ref"):
        
        mock_get_run.return_value = MagicMock(id=run_id, status="AWAITING_MERGE", approved_id="app1", commit_before="abc1234")
        mock_load.return_value = MagicMock(id=run_id, status="AWAITING_MERGE", approved_id="app1", commit_before="abc1234")
        mock_get_approved.return_value = MagicMock(draft_id="d1")
        mock_get_draft.return_value = MagicMock(
            context={"workspace_path": "/tmp/ws", "validated_task_spec": {"repo_handle": "repo_h"}}
        )
        mock_real_merge.return_value = (False, "Conflict detected")
        mock_head.return_value = "abc1234"
        
        success = await MergeGateService.perform_manual_merge(run_id)
        
        assert success is False
        mock_status.assert_any_call(run_id, "MERGE_CONFLICT", msg="manual merge failed")
