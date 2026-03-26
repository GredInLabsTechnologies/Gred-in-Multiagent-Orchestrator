import pytest
from unittest.mock import MagicMock, patch
from gimo_tui import GimoApp

@pytest.mark.asyncio
async def test_tui_header_reads_operator_status():
    """Verify TUI header consumes canonical operator status snapshot."""
    app = GimoApp(config={}, thread_id="test-thread")
    
    mock_status = {
        "repo": "test-repo",
        "branch": "main",
        "active_provider": "openai",
        "active_model": "gpt-4",
        "permissions": "full-auto",
        "budget_status": "ok",
        "context_status": "10%"
    }
    
    with patch("gimo_tui._api_request", return_value=(200, mock_status)):
        async with app.run_test() as pilot:
            app.action_refresh_all()
            await pilot.pause()
            
            header = app.query_one("#header-text")
            # In Textual, Static content can be accessed via .content property or .render()
            content = str(getattr(header, "content", header.render()))
            assert "test-repo" in content
            assert "main" in content
            assert "full-auto" in content

@pytest.mark.asyncio
async def test_tui_notices_respect_policy():
    """Verify TUI notices read from canonical notice policy endpoint."""
    app = GimoApp(config={}, thread_id="test-thread")
    
    mock_notices = [
        {"level": "warning", "message": "Test Warning"},
        {"level": "error", "message": "Test Error"}
    ]
    
    with patch("gimo_tui._api_request", return_value=(200, mock_notices)):
        async with app.run_test() as pilot:
            app.update_notices()
            await pilot.pause()
            
            notices_content = app.query_one("#notices-content")
            content = str(getattr(notices_content, "content", notices_content.render()))
            assert "Test Warning" in content
            assert "Test Error" in content

@pytest.mark.asyncio
async def test_tui_focus_mode_normalization():
    """Verify Focus mode shows concise tool summaries."""
    app = GimoApp(config={}, thread_id="test-thread")
    app.verbose = False # Focus Mode
    
    output_lines = []
    def mock_write_log(msg):
        output_lines.append(str(msg))
    
    async with app.run_test() as pilot:
        app._write_log = mock_write_log
        
        tool_data = {
            "tool_name": "search_replace",
            "arguments": {"path": "src/main.py", "old_text": "foo", "new_text": "bar"},
        }
        
        app._handle_sse_event("tool_call_start", tool_data)
        
        assert any("search_replace" in line for line in output_lines)
        assert not any('"old_text": "foo"' in line for line in output_lines)

@pytest.mark.asyncio
async def test_tui_debug_mode_normalization():
    """Verify Debug mode shows raw SSE payloads."""
    app = GimoApp(config={}, thread_id="test-thread")
    app.verbose = True # Debug Mode
    
    output_lines = []
    def mock_write_log(msg):
        output_lines.append(str(msg))
    
    async with app.run_test() as pilot:
        app._write_log = mock_write_log
        
        tool_data = {
            "tool_name": "search_replace",
            "arguments": {"path": "src/main.py", "old_text": "foo", "new_text": "bar"},
        }
        
        app._handle_sse_event("tool_call_start", tool_data)
        
        # Debug Mode shows raw args
        assert any("old_text" in line for line in output_lines)

@pytest.mark.asyncio
async def test_tui_uses_shared_slash_command_authority():
    """Verify TUI dispatches commands via shared cli_commands.py registry."""
    from cli_commands import COMMAND_REGISTRY
    assert any(cmd.name == "/status" for cmd in COMMAND_REGISTRY)
    
    app = GimoApp(config={}, thread_id="test-thread")
    async with app.run_test() as pilot:
        with patch("cli_commands.dispatch_slash_command") as mock_dispatch:
            mock_dispatch.return_value = (True, None)
            from textual.widgets import Input
            inp = app.query_one("#chat-input", Input)
            inp.value = "/status"
            app.on_input_submitted(Input.Submitted(inp, "/status"))
            mock_dispatch.assert_called_once()
