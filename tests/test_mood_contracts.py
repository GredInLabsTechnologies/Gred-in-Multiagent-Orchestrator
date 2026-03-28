from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tools.gimo_server.engine.tools.executor import ToolExecutor


@pytest.mark.asyncio
async def test_read_only_mood_blocks_mutating_tools(tmp_path):
    executor = ToolExecutor(workspace_root=str(tmp_path), mood="forensic")

    result = await executor.execute_tool_call("write_file", {"path": "x.txt", "content": "hello"})

    assert result["status"] == "error"
    assert "read-only" in result["message"].lower()


@pytest.mark.asyncio
async def test_shell_command_patterns_are_enforced(tmp_path):
    executor = ToolExecutor(workspace_root=str(tmp_path), mood="forensic")

    result = await executor.handle_shell_exec({"command": "python -V", "timeout": 1})

    assert result["status"] == "error"
    assert "not allowed" in result["message"].lower()


@pytest.mark.asyncio
async def test_web_search_results_are_filtered_by_allowed_domains(tmp_path):
    executor = ToolExecutor(workspace_root=str(tmp_path), mood="dialoger")

    fake_response = type(
        "FakeResponse",
        (),
        {
            "results": [
                type(
                    "FakeResult",
                    (),
                    {"model_dump": lambda self: {"title": "Docs", "snippet": "ok", "url": "https://docs.python.org/3/"}},
                )(),
                type(
                    "FakeResult",
                    (),
                    {"model_dump": lambda self: {"title": "Bad", "snippet": "no", "url": "https://example.com/"}},
                )(),
            ],
            "providers_used": ["duckduckgo"],
        },
    )()

    with patch("tools.gimo_server.services.web_search_service.WebSearchService.search", new=AsyncMock(return_value=fake_response)):
        result = await executor.handle_web_search({"query": "python docs"})

    assert result["status"] == "success"
    assert len(result["data"]["results"]) == 1
    assert result["data"]["results"][0]["url"].startswith("https://docs.python.org/")


@pytest.mark.asyncio
async def test_workspace_only_mood_blocks_mutations_outside_workspace(tmp_path):
    executor = ToolExecutor(workspace_root=str(tmp_path), mood="executor")
    outside = tmp_path.parent / "outside.txt"

    result = await executor.execute_tool_call("write_file", {"path": str(outside), "content": "hello"})

    assert result["status"] == "error"
    assert "inside workspace" in result["message"].lower()


@pytest.mark.asyncio
async def test_executor_write_file_reports_skipped_auto_checks_when_unavailable(tmp_path):
    executor = ToolExecutor(workspace_root=str(tmp_path), mood="executor")

    with patch("tools.gimo_server.engine.tools.executor.importlib.util.find_spec", return_value=None):
        result = await executor.handle_write_file({"path": "module.py", "content": "print('ok')\n"})

    assert result["status"] == "success"
    checks = result["data"]["checks"]
    assert any(check["kind"] == "lint" and check["status"] == "skipped" for check in checks)
    assert any(check["kind"] == "test" and check["status"] == "skipped" for check in checks)


@pytest.mark.asyncio
async def test_executor_write_file_reports_successful_auto_checks(tmp_path):
    executor = ToolExecutor(workspace_root=str(tmp_path), mood="executor")
    test_file = tmp_path / "tests" / "test_module.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    fake_results = [
        {"kind": "lint", "status": "success", "command": "python -m ruff check module.py", "output": "", "returncode": 0},
        {"kind": "test", "status": "success", "command": "python -m pytest -q tests/test_module.py", "output": "", "returncode": 0},
    ]

    with patch("tools.gimo_server.engine.tools.executor.importlib.util.find_spec", return_value=object()), patch.object(
        ToolExecutor, "_build_check_result", side_effect=fake_results
    ):
        result = await executor.handle_write_file({"path": "module.py", "content": "print('ok')\n"})

    assert result["status"] == "success"
    assert result["data"]["checks"] == fake_results


@pytest.mark.asyncio
async def test_explicit_execution_policy_overrides_mood_permissions(tmp_path):
    executor = ToolExecutor(workspace_root=str(tmp_path), mood="executor", execution_policy="read_only")

    result = await executor.execute_tool_call("write_file", {"path": "x.txt", "content": "hello"})

    assert result["status"] == "error"
    assert "read-only" in result["message"].lower()


@pytest.mark.asyncio
async def test_explicit_execution_policy_keeps_permissions_stable_across_moods(tmp_path):
    forensic_executor = ToolExecutor(
        workspace_root=str(tmp_path),
        mood="forensic",
        execution_policy="workspace_safe",
    )
    dialoger_executor = ToolExecutor(
        workspace_root=str(tmp_path),
        mood="dialoger",
        execution_policy="workspace_safe",
    )

    forensic_result = await forensic_executor.execute_tool_call("write_file", {"path": "a.txt", "content": "hello"})
    dialoger_result = await dialoger_executor.execute_tool_call("write_file", {"path": "b.txt", "content": "world"})

    assert forensic_result["status"] == "success"
    assert dialoger_result["status"] == "success"


@pytest.mark.asyncio
async def test_legacy_mood_compatibility_still_resolves_policy_when_missing(tmp_path):
    executor = ToolExecutor(workspace_root=str(tmp_path), mood="forensic")

    result = await executor.execute_tool_call("write_file", {"path": "x.txt", "content": "hello"})

    assert executor.execution_policy == "docs_research"
    assert result["status"] == "error"
    assert "read-only" in result["message"].lower()
