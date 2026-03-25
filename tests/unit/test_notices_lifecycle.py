import pytest
import time
from cli_commands import Notice
from gimo_cli_renderer import ChatRenderer
from rich.console import Console
from io import StringIO

def test_notice_dataclass():
    now = time.time()
    n = Notice(
        level="warning",
        message="Test notice",
        created_at=now,
        ttl_seconds=30,
        sticky=False
    )
    assert n.level == "warning"
    assert n.message == "Test notice"
    assert n.ttl_seconds == 30
    assert not n.sticky

def test_render_notice_inline():
    s_out = StringIO()
    console = Console(file=s_out, force_terminal=False)
    renderer = ChatRenderer(console=console)
    n = Notice(level="warning", message="High budget", created_at=time.time(), ttl_seconds=30, sticky=False)
    renderer.render_notice(n)
    output = s_out.getvalue()
    assert "High budget" in output
    assert "⚠" in output

def test_render_notice_error():
    s_out = StringIO()
    console = Console(file=s_out, force_terminal=False)
    renderer = ChatRenderer(console=console)
    n = Notice(level="error", message="Critical error", created_at=time.time(), ttl_seconds=None, sticky=True)
    renderer.render_notice(n)
    output = s_out.getvalue()
    assert "Critical error" in output
    assert "✗" in output
