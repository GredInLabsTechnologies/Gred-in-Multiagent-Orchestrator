"""R18 Change 2 — provider chokepoint tests."""
from __future__ import annotations

import pytest

from tools.gimo_server.services.provider_chokepoint import (
    InvocationRecord,
    _IN_FLIGHT,
    get_invocation_count,
    get_last_provider,
    provider_invoke,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.mark.asyncio
async def test_invoke_increments_counter_and_records_provider():
    async def _call():
        return "ok"

    rec = InvocationRecord(provider="openai", model="gpt-4o", kind="generate")
    result = await provider_invoke(rec, _call)
    assert result == "ok"
    assert get_invocation_count() == 1
    assert get_last_provider() == "openai"


@pytest.mark.asyncio
async def test_in_flight_cleared_after_call():
    async def _call():
        assert _IN_FLIGHT.get() == "anthropic/claude-opus-4-6"
        return None

    rec = InvocationRecord(provider="anthropic", model="claude-opus-4-6", kind="chat_with_tools")
    await provider_invoke(rec, _call)
    assert _IN_FLIGHT.get() is None


@pytest.mark.asyncio
async def test_nested_invoke_logs_warning(caplog):
    async def _inner():
        return "inner"

    async def _outer():
        inner_rec = InvocationRecord(provider="ollama", model="llama3", kind="generate")
        return await provider_invoke(inner_rec, _inner)

    outer_rec = InvocationRecord(provider="openai", model="gpt-4o", kind="generate")
    with caplog.at_level("WARNING"):
        await provider_invoke(outer_rec, _outer)
    assert any("nested call detected" in r.message for r in caplog.records)
    assert get_invocation_count() == 2
