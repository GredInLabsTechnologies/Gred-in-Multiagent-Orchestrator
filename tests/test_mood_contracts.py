from __future__ import annotations

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
