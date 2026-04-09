"""Circuit breaker MCP tool functional parity (R20-008).

Validates that ``gimo_trust_circuit_breaker_get`` is registered on the
governance MCP surface and that invoking it returns a well-formed
envelope wrapping ``TrustEngine.query_dimension``.
"""
from __future__ import annotations

import asyncio
import json


def test_circuit_breaker_tool_registered_and_invokable(mcp_call):
    async def _run():
        return await mcp_call(
            "gimo_trust_circuit_breaker_get",
            key="provider:anthropic",
        )

    raw = asyncio.new_event_loop().run_until_complete(_run())
    payload = json.loads(raw)
    assert "error" not in payload, payload
    assert payload["dimension_key"] == "provider:anthropic"
    assert payload["circuit_state"] in {"closed", "half_open", "open"}
    assert isinstance(payload["score"], float)


def test_circuit_breaker_tool_rejects_empty_key(mcp_call):
    async def _run():
        return await mcp_call("gimo_trust_circuit_breaker_get", key="")

    raw = asyncio.new_event_loop().run_until_complete(_run())
    payload = json.loads(raw)
    assert payload.get("error") == "key is required"
