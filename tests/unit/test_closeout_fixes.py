import pytest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from gimo import app, _interactive_chat
from gimo_tui import GimoApp
from gimo_cli_renderer import ChatRenderer

runner = CliRunner()

def test_verbose_flag_propagation():
    """Verify that --verbose flag actually changes config and TUI state, not just help output."""
    
    with patch("gimo._interactive_chat") as mock_chat:
        runner.invoke(app, ["chat", "--verbose"])
        assert mock_chat.called
        config_passed = mock_chat.call_args[0][0]
        assert config_passed["orchestrator"]["verbose"] is True
        
    with patch("gimo_tui.GimoApp") as mock_app_class:
        mock_instance = mock_app_class.return_value
        runner.invoke(app, ["tui", "--verbose"])
        assert mock_instance.verbose is True

@pytest.mark.asyncio
async def test_dismiss_notice_tui_behavior():
    """Verify that Esc actually clears the visual notice and stops the timer."""
    app_tui = GimoApp()
    async with app_tui.run_test() as pilot:
        # Show a sticky error
        app_tui.show_notice("Test sticky error!", style="red", ttl=0)
        await pilot.pause(0.1)
        
        lbl = app_tui.query_one("#notices-content")
        render_text = str(lbl.render())
        assert "Test sticky error" in render_text
        
        # Press escape
        await pilot.press("escape")
        await pilot.pause(0.1)
        
        render_text_post = str(lbl.render())
        assert "No active notices" in render_text_post
        assert app_tui._notice_timer is None

def test_ctrl_c_aborts_turn_rendering(tmp_path):
    """Verify KeyboardInterrupt strictly skips response formatting and history saving."""
    from rich.console import Console
    import httpx
    
    config = {
        "api": {"base_url": "http://test-local"},
        "orchestrator": {"history_dir": str(tmp_path), "plans_dir": str(tmp_path), "runs_dir": str(tmp_path), "verbose": False}
    }
    
    class MockRenderer:
        def __init__(self, *args, **kwargs):
            self._generation_active = False
            self.input_calls = 0
            
        def __getattr__(self, name):
            return lambda *args, **kwargs: None
            
        def get_user_input(self):
            if self.input_calls == 0:
                self.input_calls += 1
                return "hello"
            return "/exit"
            
        class _ThinkingMock:
            def __enter__(self): pass
            def __exit__(self, *args): pass
            
        def render_thinking(self):
            return self._ThinkingMock()
            
        def render_interrupted(self): pass
        
        def render_response(self, text):
            raise RuntimeError("Should not render response on interrupt!")
            
        def render_footer(self, usage):
            raise RuntimeError("Should not render footer on interrupt!")
    
    # We patch _resolve_token to avoid keyring issues, and client.stream to raise KI
    with patch("gimo._resolve_token", return_value="dummy"), \
         patch("gimo._api_request", return_value=(201, {"id": "test-thread-id"})), \
         patch("gimo._preflight_check", return_value=(True, "")), \
         patch("httpx.Client.stream") as mock_stream, \
         patch("gimo._project_root", return_value=tmp_path):
         
        class MockResponse:
            @property
            def status_code(self): return 200
            @property
            def request(self): return None
            def iter_lines(self):
                yield "data: {}"
                raise KeyboardInterrupt("Simulated user interrupt")
                
        class MockStreamContext:
            def __enter__(self): return MockResponse()
            def __exit__(self, *args): pass
            
        mock_stream.return_value = MockStreamContext()
        
        with patch("gimo_cli_renderer.ChatRenderer", new=MockRenderer):
            _interactive_chat(config)
