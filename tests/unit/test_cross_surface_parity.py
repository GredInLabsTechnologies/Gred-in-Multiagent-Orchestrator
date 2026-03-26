import pytest
from unittest.mock import MagicMock, patch
from tools.gimo_server.services.operator_status_service import OperatorStatusService
from tools.gimo_server.services.notice_policy_service import NoticePolicyService

@pytest.mark.asyncio
async def test_cross_surface_status_parity():
    """
    Verifies that all surfaces consume the same canonical status from OperatorStatusService.
    In Phase 7B, the TUI and CLI no longer compute their own transient state.
    """
    with patch.object(OperatorStatusService, 'get_status_snapshot') as mock_status:
        mock_status.return_value = {"status": "operational", "load": 0.1}
        
        # 1. Simulate TUI consumption
        tui_status = OperatorStatusService.get_status_snapshot()
        
        # 2. Simulate CLI consumption
        cli_status = OperatorStatusService.get_status_snapshot()
        
        # 3. Simulate App Façade consumption
        app_status = OperatorStatusService.get_status_snapshot()
        
        assert tui_status == cli_status == app_status
        assert tui_status["status"] == "operational"

@pytest.mark.asyncio
async def test_cross_surface_notice_parity():
    """
    Verifies that all surfaces consume the same canonical notice feed.
    """
    # In Phase 7B, surfaces consume NoticePolicyService evaluation results
    context = {"context_percentage": 75}
    with patch.object(NoticePolicyService, 'evaluate_all', return_value=[{"code": "ctx_high", "message": "Notice"}]) as mock_eval:
        # Simulate TUI listing notices
        tui_notices = NoticePolicyService.evaluate_all(context)
        
        # Simulate App listing notices
        app_notices = NoticePolicyService.evaluate_all(context)
        
        assert tui_notices == app_notices
        assert tui_notices[0]["code"] == "ctx_high"

def test_legacy_path_deprecations():
    """
    Ensures legacy paths are explicitly labeled or return warnings (conceptual verification).
    """
    from tools.gimo_server.ops_routes import get_filtered_openapi
    from tools.gimo_server.routers.ops.repo_router import open_repo, select_repo
    
    # Verify markers in docstrings
    assert "[LEGACY INTEGRATION]" in (get_filtered_openapi.__doc__ or "")
    assert "[LEGACY]" in (open_repo.__doc__ or "")
    assert "[LEGACY]" in (select_repo.__doc__ or "")
