import pytest
from gimo_cli_renderer import ChatRenderer
from rich.console import Console
from io import StringIO

def test_post_run_report_full_data():
    s_out = StringIO()
    console = Console(file=s_out, force_terminal=False)
    renderer = ChatRenderer(console=console)
    
    usage = {"total_tokens": 1500, "cost_usd": 0.015}
    run_data = {
        "id": "run-123",
        "objective": "Refactor router",
        "tools_used": ["t1", "t2"],
        "modified_files": ["foo.py"],
        "lines_added": 10,
        "lines_removed": 5,
        "duration": 4.5,
        "tests": {"passed": 3, "total": 3},
        "rollback_plan": ["git revert 1234abc"],
        "alerts": ["Warning: deprecation"]
    }
    
    renderer.render_post_run_report(run_id="run-123", usage=usage, run_data=run_data)
    output = s_out.getvalue()
    
    assert "Refactor router" in output
    assert "1 tocados" in output
    assert "Tools: 2" in output
    assert "Tests: 3/3 ✓" in output
    assert "Diff: +10 -5 líneas" in output
    assert "Coste: $0.0150" in output
    assert "Duración: 4.5s" in output
    assert "git revert 1234abc" in output
    assert "Warning: deprecation" in output

def test_post_run_report_missing_data_uses_na():
    s_out = StringIO()
    console = Console(file=s_out, force_terminal=False)
    renderer = ChatRenderer(console=console)
    
    usage = {}
    run_data = {}
    
    renderer.render_post_run_report(run_id=None, usage=usage, run_data=run_data)
    output = s_out.getvalue()
    
    assert "Objetivo: n/a" in output
    assert "Ficheros: 0 tocados" in output
    assert "Tools: 0" in output
    assert "Tests: n/a" in output
    assert "Diff: n/a" in output
    assert "Coste: n/a" in output
    assert "Duración: n/a" in output
    assert "Rollback: n/a" in output
    assert "Alertas: ninguna" in output
