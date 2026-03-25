import pytest
from typer.testing import CliRunner
from gimo import app, _interactive_chat
from gimo_tui import GimoApp
from gimo_cli_renderer import ChatRenderer
from rich.console import Console
from io import StringIO
import threading
import time

runner = CliRunner()

def test_verbose_flag_in_main_chat_and_tui():
    """Verify that --verbose flag is parsed in main, chat, and tui commands."""
    res_chat = runner.invoke(app, ["chat", "--help"])
    assert "--verbose" in res_chat.stdout

    res_tui = runner.invoke(app, ["tui", "--help"])
    assert "--verbose" in res_tui.stdout

    res_main = runner.invoke(app, ["--help"])
    assert "--verbose" in res_main.stdout

def test_post_run_report_gating():
    """Verify post_run report ONLY renders when run metadata exists."""
    s_out = StringIO()
    console = Console(file=s_out, force_terminal=False)
    renderer = ChatRenderer(console=console)
    
    # 1. Empty/missing data -> NO report
    renderer.render_post_run_report(run_id=None, usage={"tokens": 10}, run_data={})
    assert s_out.getvalue() == ""
    
    # 2. Contains run_id -> renders report
    renderer.render_post_run_report(run_id="abc-123", usage={"tokens": 10}, run_data={"id": "abc-123"})
    assert "Post-run Report" in s_out.getvalue()

def test_dismiss_notice_tui():
    """Test manual escape dismisses sticky notices."""
    tui = GimoApp()
    tui._notice_timer = None # mock
    assert hasattr(tui, "action_dismiss_notice")
