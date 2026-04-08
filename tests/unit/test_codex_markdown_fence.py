"""R18 Change 6 — Codex markdown-fenced JSON parser."""
from tools.gimo_server.adapters.codex import _strip_markdown_fence


def test_strip_json_fence():
    assert _strip_markdown_fence('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_bare_fence():
    assert _strip_markdown_fence('```\n{"a": 1}\n```') == '{"a": 1}'


def test_leaves_unfenced_text_untouched():
    assert _strip_markdown_fence('{"a": 1}') == '{"a": 1}'


def test_handles_empty():
    assert _strip_markdown_fence('') == ''
