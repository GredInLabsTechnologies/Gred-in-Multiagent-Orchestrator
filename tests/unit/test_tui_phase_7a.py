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
    """Verify TUI notices read from the authoritative status snapshot alerts."""
    app = GimoApp(config={}, thread_id="test-thread")
    calls: list[str] = []
    
    mock_status = {
        "repo": "test-repo",
        "branch": "main",
        "active_provider": "openai",
        "active_model": "gpt-4",
        "permissions": "suggest",
        "budget_status": "ok",
        "budget_percentage": 80.0,
        "context_status": "10%",
        "alerts": [
            {"level": "warning", "message": "Test Warning"},
            {"level": "error", "message": "Test Error"},
        ],
    }
    
    def _fake_api_request(config, method, path, **kwargs):
        del config, method, kwargs
        calls.append(path)
        return 200, mock_status

    with patch("gimo_tui._api_request", side_effect=_fake_api_request):
        async with app.run_test() as pilot:
            calls.clear()
            app.update_notices()
            await pilot.pause()
            
            notices_content = app.query_one("#notices-content")
            content = str(getattr(notices_content, "content", notices_content.render()))
            assert calls == ["/ops/operator/status"]
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
            await pilot.pause()
            mock_dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_tui_done_event_does_not_render_noncanonical_post_run_report():
    app = GimoApp(config={}, thread_id="test-thread")

    async with app.run_test() as pilot:
        with patch.object(app, "_render_tui_post_run_report", side_effect=AssertionError("must stay unused")):
            app._handle_sse_event(
                "done",
                {"usage": {"total_tokens": 5}, "run_report": {"goal": "ignored"}},
            )
            await pilot.pause()


@pytest.mark.asyncio
async def test_tui_ctrl_c_interrupts_active_turn_without_quitting():
    app = GimoApp(config={}, thread_id="test-thread")
    closed = {"value": False}

    class FakeResponse:
        def close(self):
            closed["value"] = True

    async with app.run_test() as pilot:
        with patch.object(app, "exit") as mock_exit:
            app._stream_active = True
            app._active_response = FakeResponse()
            app.action_interrupt_or_quit()
            await pilot.pause()

            assert closed["value"] is True
            assert app._interrupt_requested is True
            mock_exit.assert_not_called()


@pytest.mark.asyncio
async def test_tui_reset_requires_confirmation_before_backend_reset():
    app = GimoApp(config={}, thread_id="thread-123")
    calls: list[tuple[str, str]] = []

    def _fake_api_request(config, method, path, **kwargs):
        del config, kwargs
        calls.append((method, path))
        if path == "/ops/threads/thread-123/reset":
            return 204, {}
        if path == "/ops/operator/status":
            return 200, {"repo": "repo", "branch": "main", "active_provider": "openai", "active_model": "gpt-5", "alerts": []}
        raise AssertionError(path)

    async with app.run_test() as pilot:
        with patch("gimo_tui._api_request", side_effect=_fake_api_request):
            from textual.widgets import Input
            calls.clear()

            inp = app.query_one("#chat-input", Input)
            inp.value = "/reset"
            app.on_input_submitted(Input.Submitted(inp, "/reset"))
            await pilot.pause()

            assert calls == []

            inp.value = "y"
            app.on_input_submitted(Input.Submitted(inp, "y"))
            await pilot.pause()

            assert ("POST", "/ops/threads/thread-123/reset") in calls
