"""Tests for the declarative CLI response renderer."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from gimo_cli.render import TRACES, TableSpec, render_response


@pytest.fixture(autouse=True)
def _patch_console(monkeypatch):
    """Redirect render output to a capturable StringIO."""
    buf = StringIO()
    test_console = Console(file=buf, force_terminal=True, width=120)
    monkeypatch.setattr("gimo_cli.render.console", test_console)
    monkeypatch.setattr("gimo_cli.console", test_console)
    return buf


def test_render_list_as_table(_patch_console):
    spec = TableSpec(title="Items", columns=["id", "name"])
    render_response([{"id": "1", "name": "alpha"}, {"id": "2", "name": "beta"}], spec)
    output = _patch_console.getvalue()
    assert "alpha" in output
    assert "beta" in output


def test_render_unwrapped_dict(_patch_console):
    spec = TableSpec(title="Traces", columns=["id", "status"], unwrap="items")
    render_response({"items": [{"id": "t1", "status": "ok"}], "count": 1}, spec)
    output = _patch_console.getvalue()
    assert "t1" in output


def test_render_empty_list(_patch_console):
    spec = TableSpec(title="Empty", columns=["a"], empty_msg="Nothing here.")
    render_response([], spec)
    output = _patch_console.getvalue()
    assert "Nothing here." in output


def test_render_empty_wrapped(_patch_console):
    spec = TableSpec(title="Traces", columns=["id"], unwrap="items", empty_msg="No traces.")
    render_response({"items": [], "count": 0}, spec)
    output = _patch_console.getvalue()
    assert "No traces." in output


def test_render_sections(_patch_console):
    spec = TableSpec(
        title="Multi",
        columns=[],
        sections={
            "installed": TableSpec(title="Installed", columns=["id"]),
            "available": TableSpec(title="Available", columns=["id"]),
        },
    )
    render_response({"installed": [{"id": "m1"}], "available": [{"id": "m2"}]}, spec)
    output = _patch_console.getvalue()
    assert "m1" in output
    assert "m2" in output


def test_render_sections_all_empty(_patch_console):
    spec = TableSpec(
        title="Multi",
        columns=[],
        sections={"a": TableSpec(title="A", columns=["x"]), "b": TableSpec(title="B", columns=["x"])},
        empty_msg="All empty.",
    )
    render_response({"a": [], "b": []}, spec)
    output = _patch_console.getvalue()
    assert "All empty." in output


def test_render_json_flag_bypasses(_patch_console, monkeypatch):
    """When json_output=True, raw JSON is emitted, not a table."""
    emitted = {}

    def fake_emit(payload, *, json_output):
        emitted["payload"] = payload
        emitted["json"] = json_output

    monkeypatch.setattr("gimo_cli.render.emit_output", fake_emit)
    spec = TableSpec(title="X", columns=["a"])
    render_response([{"a": 1}], spec, json_output=True)
    assert emitted["json"] is True


def test_render_summary_line(_patch_console):
    spec = TableSpec(
        title="Analytics",
        columns=[],
        sections={"by_model": TableSpec(title="By Model", columns=["model", "cost"])},
        summary=lambda p: f"Savings: ${p.get('total_savings', 0):.2f}",
    )
    render_response({"by_model": [{"model": "gpt-4", "cost": "1.5"}], "total_savings": 3.14}, spec)
    output = _patch_console.getvalue()
    assert "3.14" in output


def test_render_traces_uses_trace_id_column(_patch_console):
    render_response(
        {"items": [{"trace_id": "trace-123", "status": "completed", "duration_ms": 42}], "count": 1},
        TRACES,
    )
    output = _patch_console.getvalue()
    assert "trace-123" in output
