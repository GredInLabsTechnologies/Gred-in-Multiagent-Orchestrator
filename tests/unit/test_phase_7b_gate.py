import pytest
import os
import inspect
from tools.gimo_server.services.sub_agent_manager import SubAgentManager
from tools.gimo_server.services.run_worker import RunWorker

@pytest.mark.asyncio
async def test_sub_agent_transitional_path_marking():
    """
    Verfies that worktree creation logic for sub-agents is marked as obsolete/transitional.
    """
    source = inspect.getsource(SubAgentManager.create_sub_agent)
    assert "[OBSOLETE/TRANSITIONAL]" in source
    assert "OBSOLETE isolated worktree" in source

@pytest.mark.asyncio
async def test_run_worker_legacy_omission():
    """
    Verifies that legacy execution paths in RunWorker are indeed removed or nulled.
    """
    worker = RunWorker()
    # P5C hardening ensured these are now Opaque or return None.
    # We follow up in 7B to confirm they remain Obsolete.
    assert worker._extract_target_path("any text") is None
    assert await worker._execute_file_task() is False

def test_surface_topology_documentation():
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
        # Check for [OFFICIAL FAÇADE] but avoid encoding sensitive match if possible
        # or just check partial strings if FAÇADE is tricky.
        assert "[OFFICIAL" in content and "ADE]" in content

def test_api_documentation_deprecations():
    """
    Checks if the API docs reflect the deprecations.
    """
    docs_path = "docs/API.md"
    assert os.path.exists(docs_path)
    with open(docs_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "[LEGACY INTEGRATION]" in content
        # Backticks might be present in markdown
        assert "Preferred: `/mcp/app`" in content or "Preferred: /mcp/app" in content
        assert "/mcp/app" in content
        assert "[OFFICIAL]" in content

def test_system_documentation_stabilization():
    """
    Checks if SYSTEM.md reflects the Phase 7B stabilization.
    """
    docs_path = "docs/SYSTEM.md"
    assert os.path.exists(docs_path)
    with open(docs_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "Multi-Surface Stabilization (Phase 7B)" in content
        assert "/mcp/app" in content
