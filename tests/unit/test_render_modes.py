import pytest
from gimo_cli_renderer import ChatRenderer
from rich.console import Console
from io import StringIO

def test_render_tool_call_focus_mode():
    s_out = StringIO()
    console = Console(file=s_out, force_terminal=False)
    # Default is Focus Mode (verbose=False)
    renderer = ChatRenderer(console=console, verbose=False)
    
    renderer.render_tool_call_start("search_code", {"query": "def foo()"}, risk="LOW")
    output = s_out.getvalue()
    
    # Should show summary but not raw json dumps
    assert "search_code" in output
    assert "query=def foo()" in output
    assert "{" not in output  # No raw JSON dump
    assert "..." in output

def test_render_tool_call_debug_mode():
    s_out = StringIO()
    console = Console(file=s_out, force_terminal=False)
    # Verbose Mode
    renderer = ChatRenderer(console=console, verbose=True)
    
    renderer.render_tool_call_start("search_code", {"query": "def foo()", "extra": "long payload"}, risk="LOW")
    output = s_out.getvalue()
    
    # Should include raw JSON payload
    assert "search_code" in output
    assert "query=def foo()" in output
    assert '{"query": "def foo()", "extra": "long payload"}' in output

def test_render_sse_raw_ignored_in_focus():
    s_out = StringIO()
    console = Console(file=s_out, force_terminal=False)
    renderer = ChatRenderer(console=console, verbose=False)
    
    renderer.render_sse_raw("tool_call_start", '{"tool_name": "test"}')
    output = s_out.getvalue()
    assert output == ""  # Nothing printed

def test_render_sse_raw_printed_in_debug():
    s_out = StringIO()
    console = Console(file=s_out, force_terminal=False)
    renderer = ChatRenderer(console=console, verbose=True)
    
    renderer.render_sse_raw("tool_call_start", '{"tool_name": "test"}')
    output = s_out.getvalue()
    assert "SSE Event:" in output
    assert "tool_call_start" in output
    assert '{"tool_name": "test"}' in output
