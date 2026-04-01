from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_setup_mcp_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "setup_mcp.py"
    spec = importlib.util.spec_from_file_location("setup_mcp", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_merge_codex_config_text_appends_managed_block(tmp_path):
    setup_mcp = _load_setup_mcp_module()

    existing = 'model = "gpt-5.4"\n'
    merged = setup_mcp._merge_codex_config_text(existing, tmp_path)

    assert setup_mcp.CODEX_GIMO_BEGIN in merged
    assert setup_mcp.CODEX_GIMO_END in merged
    assert "[mcp_servers.gimo]" in merged
    assert "command = 'cmd.exe'" in merged
    assert f"cwd = '{tmp_path}'" in merged


def test_merge_codex_config_text_replaces_existing_gimo_block(tmp_path):
    setup_mcp = _load_setup_mcp_module()

    existing = (
        'model = "gpt-5.4"\n\n'
        "[mcp_servers.gimo]\n"
        "enabled = false\n"
        "command = 'old.exe'\n"
        "\n"
        "[features]\n"
        "multi_agent = true\n"
    )

    merged = setup_mcp._merge_codex_config_text(existing, tmp_path)

    assert merged.count("[mcp_servers.gimo]") == 1
    assert "command = 'old.exe'" not in merged
    assert "command = 'cmd.exe'" in merged
    assert "[features]" in merged


def test_strip_codex_managed_block_removes_only_gimo_section():
    setup_mcp = _load_setup_mcp_module()

    existing = (
        'model = "gpt-5.4"\n\n'
        f"{setup_mcp.CODEX_GIMO_BEGIN}\n"
        "[mcp_servers.gimo]\n"
        "enabled = true\n"
        f"{setup_mcp.CODEX_GIMO_END}\n\n"
        "[features]\n"
        "multi_agent = true\n"
    )

    stripped, removed = setup_mcp._strip_codex_managed_block(existing)

    assert removed is True
    assert "[mcp_servers.gimo]" not in stripped
    assert "[features]" in stripped
