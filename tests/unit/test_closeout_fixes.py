import pytest
import shutil
import io
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from gimo import app, _interactive_chat
from gimo_tui import GimoApp
from gimo_cli_renderer import ChatRenderer
from rich.console import Console
import httpx

runner = CliRunner()

def test_verbose_flag_propagation():
    """Verify that --verbose flag actually produces verbose behavioral output."""
    s_out = io.StringIO()
    c = Console(file=s_out, force_terminal=False)
    
    # Verbose True
    cr_verbose = ChatRenderer(console=c, verbose=True)
    cr_verbose.render_tool_call_start("foo", {"arg": "val"}, "LOW")
    out_verbose = s_out.getvalue()
    
    # Verbose False
    s_out = io.StringIO()
    c = Console(file=s_out, force_terminal=False)
    cr_focus = ChatRenderer(console=c, verbose=False)
    cr_focus.render_tool_call_start("foo", {"arg": "val"}, "LOW")
    out_focus = s_out.getvalue()
    
    assert "{" in out_verbose  # raw json dumped in verbose
    assert "{" not in out_focus

@pytest.mark.asyncio
async def test_dismiss_notice_tui_behavior():
    """Verify that Esc actually clears the visual notice and stops the timer."""
    app_tui = GimoApp()
    async with app_tui.run_test() as pilot:
        app_tui.show_notice("Test sticky error!", style="red", ttl=0)
        await pilot.pause(0.1)
        lbl = app_tui.query_one("#notices-content")
        render_text = str(lbl.render())
        assert "Test sticky error" in render_text
        
        await pilot.press("escape")
        await pilot.pause(0.1)
        render_text_post = str(lbl.render())
        assert "No active notices" in render_text_post
        assert app_tui._notice_timer is None

def test_ctrl_c_aborts_turn_rendering_sse_path(tmp_path):
    """Verify KeyboardInterrupt skips response formatting in SSE path."""
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
            
        def render_thinking(self): return self._ThinkingMock()
        def render_interrupted(self): pass
        
        def render_response(self, text):
            raise RuntimeError("Should not render response on interrupt!")
        def render_footer(self, usage):
            raise RuntimeError("Should not render footer on interrupt!")
        def render_post_run_report(self, run_id, usage, run_data):
            raise RuntimeError("Should not render post-run report on interrupt!")
    
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

def test_ctrl_c_aborts_turn_rendering_sync_fallback_path(tmp_path):
    """Verify KeyboardInterrupt skips response formatting in sync fallback path."""
    config = {
        "api": {"base_url": "http://test-local"},
        "orchestrator": {"history_dir": str(tmp_path), "plans_dir": str(tmp_path), "runs_dir": str(tmp_path), "verbose": False}
    }
    
    class MockRenderer:
        def __init__(self, *args, **kwargs):
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
            
        def render_thinking(self): return self._ThinkingMock()
        def render_interrupted(self): pass
        
        def render_response(self, text):
            raise RuntimeError("Should not render response on sync interrupt!")
        def render_footer(self, usage):
            raise RuntimeError("Should not render footer on sync interrupt!")
        def render_post_run_report(self, run_id, usage, run_data):
            raise RuntimeError("Should not render post-run report on sync interrupt!")
    
    with patch("gimo._resolve_token", return_value="dummy"), \
         patch("gimo._api_request", return_value=(201, {"id": "test-thread-id"})), \
         patch("gimo._preflight_check", return_value=(True, "")), \
         patch("gimo._project_root", return_value=tmp_path):
         
        def mock_stream(*args, **kwargs):
            raise httpx.HTTPStatusError("Mock failure", request=MagicMock(), response=MagicMock())
            
        def mock_post(*args, **kwargs):
            raise KeyboardInterrupt("Simulated sync user interrupt")
            
        with patch("httpx.Client.stream", side_effect=mock_stream), \
             patch("httpx.Client.post", side_effect=mock_post), \
             patch("gimo_cli_renderer.ChatRenderer", new=MockRenderer):
            _interactive_chat(config)
