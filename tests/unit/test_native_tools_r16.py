"""R16 regression coverage for native MCP tools.

Covers:
1. gimo_generate_team_config aborts when the in-place draft PUT fails
   (proxy_to_api returns "❌ Error" string instead of raising).
2. gimo_chat fire-and-return contract: returns immediately with thread_id
   and dispatches the chat in a background task.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tools.gimo_server.mcp_bridge import native_tools


class _FakeMCP:
    """Minimal stand-in for FastMCP that captures registered tool callables."""

    def __init__(self) -> None:
        self.tools: dict[str, callable] = {}

    def tool(self):
        def _decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return _decorator


@pytest.fixture
def registered_tools():
    mcp = _FakeMCP()
    native_tools.register_native_tools(mcp)
    return mcp.tools


# ── Fix #P2: gimo_generate_team_config must verify the materialization PUT ──

@pytest.mark.asyncio
async def test_generate_team_config_aborts_on_empty_draft(registered_tools):
    """R17.1 contract: /ops/generate-plan is the single authoritative
    materialization path. The bridge no longer maintains a parallel
    in-place PUT pipeline, so a draft that lacks content must surface as
    an error rather than being silently re-materialized.

    R18 update: test rewritten to match the current R17.1 contract —
    the previous assertion about "Failed to persist" referred to an
    obsolete in-place PUT branch that was removed in R17.1.
    """
    gimo_generate_team_config = registered_tools["gimo_generate_team_config"]

    get_response = "✅ Success (200):\n" + json.dumps({
        "id": "d_test",
        "content": None,
        "prompt": "Build a hello-world worker",
        "context": {},
    })

    async def fake_proxy(method, path, **kwargs):
        if method == "GET":
            return get_response
        return "✅ Success (200):\n{}"

    with patch.object(native_tools, "logger"), \
         patch("tools.gimo_server.mcp_bridge.bridge.proxy_to_api", side_effect=fake_proxy):
        result = await gimo_generate_team_config("d_test")

    parsed = json.loads(result)
    assert "error" in parsed, f"expected error JSON, got: {result}"
    assert "d_test" in parsed["error"]
    assert "not found or empty" in parsed["error"]


# ── Fix #2/#3: gimo_chat fire-and-return contract ──────────────────────────

@pytest.mark.asyncio
async def test_gimo_chat_fire_and_return_dispatches_background(registered_tools):
    """gimo_chat must return immediately with the thread_id and schedule a
    background task for the actual /chat call (which can take minutes)."""
    gimo_chat = registered_tools["gimo_chat"]

    create_thread_resp = SimpleNamespace(
        status_code=201,
        json=lambda: {"id": "th_abc"},
        text="",
    )

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, **kw):
            return create_thread_resp

    # Snapshot tasks before so we can detect new ones.
    pre_tasks = set(native_tools._BACKGROUND_CHAT_TASKS)

    with patch("httpx.AsyncClient", _FakeClient), \
         patch("tools.gimo_server.mcp_bridge.bridge._get_auth_token", return_value="t"):
        result = await gimo_chat("hello world")
        # Foreground returned. Cancel any background task scheduled by the tool
        # BEFORE leaving the patch context — we don't want it to make real HTTP.
        new_tasks = native_tools._BACKGROUND_CHAT_TASKS - pre_tasks
        for task in new_tasks:
            task.cancel()
        for task in new_tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    assert "th_abc" in result
    assert "fire-and-return" in result.lower()
    assert "Thread ID: th_abc" in result
    # A background task was scheduled and tracked (proving fire-and-return,
    # not synchronous wait).
    assert len(new_tasks) == 1
