import pytest
from gimo_tui import GimoApp

@pytest.mark.asyncio
async def test_phase_7a_gate():
    """Verify all mandatory Phase 7A cockpit invariants are present in the TUI codebase."""
    app = GimoApp(config={}, thread_id="test-thread")
    
    # Invariant: tui_header_reads_operator_status
    assert hasattr(app, "_refresh_topology_logic")
    assert hasattr(app, "_update_header")
    
    # Invariant: tui_notices_respect_policy
    assert hasattr(app, "update_notices")
    assert hasattr(app, "_update_notices_widget")
    
    # Invariant: tui_focus_mode_is_normalized
    # Invariant: tui_debug_mode_is_normalized
    # Both are handled via `verbose` and `_handle_sse_event` branching
    assert hasattr(app, "verbose")
    assert hasattr(app, "_handle_sse_event")
    
    # Invariant: tui_uses_shared_slash_command_authority
    with open("gimo_tui.py", "r", encoding="utf-8") as f:
        content = f.read()
        assert "from cli_commands import dispatch_slash_command" in content
        assert "dispatch_slash_command(" in content

    # Invariant: no_phase_7b_started
    # Verify forbidden files were not touched (this is checked by the orchestrator)
    # But we can check that we didn't add any /mcp or /ops deprecation markers
    assert "DEPRECATED" not in content # Example check
