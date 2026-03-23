from __future__ import annotations

import pytest
import respx
from httpx import Response

from tools.gimo_server.providers.openai_compat import OpenAICompatAdapter


@pytest.mark.asyncio
@respx.mock
async def test_chat_with_tools_includes_max_tokens_and_ignores_response_format_with_tools():
    adapter = OpenAICompatAdapter(base_url="http://localhost:9999/v1", model="test-model", api_key="test")
    route = respx.post("http://localhost:9999/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "ok", "tool_calls": []}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        )
    )

    result = await adapter.chat_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "noop", "parameters": {"type": "object", "properties": {}}}}],
        max_tokens=42,
        response_format={"type": "json_object"},
    )

    assert result["content"] == "ok"
    sent = route.calls[0].request.content.decode("utf-8")
    assert '"max_tokens":42' in sent
    assert '"response_format"' not in sent


@pytest.mark.asyncio
@respx.mock
async def test_chat_with_tools_passes_response_format_without_tools():
    adapter = OpenAICompatAdapter(base_url="http://localhost:9998/v1", model="test-model", api_key="test")
    route = respx.post("http://localhost:9998/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        )
    )

    await adapter.chat_with_tools(
        messages=[{"role": "user", "content": "json please"}],
        tools=None,
        response_format={"type": "json_object"},
    )

    sent = route.calls[0].request.content.decode("utf-8")
    assert '"response_format":{"type":"json_object"}' in sent
