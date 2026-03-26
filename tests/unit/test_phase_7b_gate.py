import pytest
import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch
from tools.gimo_server.services.sub_agent_manager import SubAgentManager
from tools.gimo_server.services.run_worker import RunWorker
from tools.gimo_server.services.operator_status_service import OperatorStatusService
from tools.gimo_server.services.notice_policy_service import NoticePolicyService

@pytest.mark.asyncio
async def test_sub_agent_refuses_root_worktree_fallback():
    """
    WP-01/GAP-01: Verifies that SubAgentManager no longer creates worktrees 
    from the source repository root by default.
    """
    # Attempt to create a sub-agent without a provisioned workspace_path
    # This should now raise a ValueError instead of falling back to REPO_ROOT_DIR.
    request = {"modelPreference": "test-model", "constraints": {}}
    
    with pytest.raises(ValueError) as excinfo:
        await SubAgentManager.create_sub_agent(parent_id="test", request=request)
    
    assert "workspace_path is required" in str(excinfo.value)
    assert "[OBSOLETE/TRANSITIONAL]" not in str(excinfo.value) # We want a clean error

@pytest.mark.asyncio
async def test_sub_agent_uses_provisioned_workspace():
    """
    Verifies that SubAgentManager correctly uses a provisioned workspace path.
    """
    sub_id = str(uuid.uuid4())
    fake_workspace = Path("/tmp/fake-workspace")
    request = {
        "modelPreference": "test-model", 
        "workspace_path": str(fake_workspace)
    }
    
    with patch("tools.gimo_server.services.sub_agent_manager.SubAgentManager._persist"):
        agent = await SubAgentManager.create_sub_agent(parent_id="test", request=request)
        assert agent.worktreePath == str(fake_workspace)
        assert agent.status == "starting"

@pytest.mark.asyncio
async def test_operator_status_contract_honesty():
    """
    WP-03/GAP-03: Verifies that OperatorStatusService provides a backend-authored snapshot.
    """
    snapshot = OperatorStatusService.get_status_snapshot()
    
    # Core fields must be present
    assert "repo" in snapshot
    assert "branch" in snapshot
    assert "active_provider" in snapshot
    assert "active_model" in snapshot
    assert "backend_version" in snapshot
    assert "alerts" in snapshot
    
    # Verify that it doesn't contain synthetic or stubbed PII
    assert "user_email" not in snapshot
    assert "fake_metric" not in snapshot

@pytest.mark.asyncio
async def test_notice_policy_backend_authored():
    """
    WP-03/GAP-03: Verifies that NoticePolicyService generates authoritative notices.
    """
    # Mock a high budget context
    context = {
        "budget_percentage": 85.0,
        "context_percentage": 75.0,
        "merge_base_drift": True
    }
    
    notices = NoticePolicyService.evaluate_all(context)
    codes = [n["code"] for n in notices]
    
    assert "budget_high" in codes
    assert "ctx_high" in codes
    assert "merge_base_drift" in codes
    assert all("level" in n and "message" in n for n in notices)

def test_surface_topology_documentation_finalized():
    """
    Checks if the finalized topology and client facades are in the authoritative docs.
    """
    docs_path = "docs/CLIENT_SURFACES.md"
    assert os.path.exists(docs_path)
    with open(docs_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "[Phase 7B Verified]" in content
        assert "Parity Closure (Cross-Surface Invariants)" in content
        assert "/mcp/app" in content
        assert "[OFFICIAL FAÇADE]" in content

def test_api_documentation_deprecations_finalized():
    """
    Checks if the API docs reflect the deprecations.
    """
    docs_path = "docs/API.md"
    assert os.path.exists(docs_path)
    with open(docs_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "[LEGACY INTEGRATION]" in content
        assert "Preferred: `/mcp/app`" in content
        assert "[OFFICIAL]" in content
