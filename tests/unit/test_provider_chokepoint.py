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


# ── Layer 2 (httpx transport guard) ────────────────────────────────────────


def test_layer2_is_provider_host_matches_suffixes():
    from tools.gimo_server.services.provider_chokepoint import _is_provider_host

    assert _is_provider_host("api.openai.com")
    assert _is_provider_host("foo.api.openai.com")
    assert _is_provider_host("api.anthropic.com")
    assert not _is_provider_host("example.com")
    assert not _is_provider_host(None)


def test_layer2_transport_guard_strict_blocks_off_context(caplog, monkeypatch):
    import httpx
    import tools.gimo_server.services.provider_chokepoint as pc
    from tools.gimo_server.services.provider_chokepoint import (
        ProviderChokepointError,
        install_transport_guard,
        get_bypass_log,
    )

    # Snapshot originals so we can restore after the test — otherwise the
    # strict guard persists and breaks subsequent tests that hit provider hosts.
    orig_async = httpx.AsyncHTTPTransport.handle_async_request
    orig_sync = httpx.HTTPTransport.handle_request
    orig_flag = pc._LAYER2_INSTALLED
    pc._LAYER2_INSTALLED = False

    def _restore():
        httpx.AsyncHTTPTransport.handle_async_request = orig_async
        httpx.HTTPTransport.handle_request = orig_sync
        pc._LAYER2_INSTALLED = orig_flag

    monkeypatch.setattr(pc, "_LAYER2_INSTALLED", False, raising=False)

    try:
        install_transport_guard(strict=True)

        client = httpx.Client(transport=httpx.HTTPTransport())
        with pytest.raises(ProviderChokepointError):
            try:
                client.get("https://api.openai.com/v1/models", timeout=0.001)
            finally:
                client.close()
        assert any(e["host"] == "api.openai.com" for e in get_bypass_log())
    finally:
        _restore()


def test_layer2_install_is_idempotent(monkeypatch):
    import httpx
    import tools.gimo_server.services.provider_chokepoint as pc
    from tools.gimo_server.services.provider_chokepoint import install_transport_guard

    orig_async = httpx.AsyncHTTPTransport.handle_async_request
    orig_sync = httpx.HTTPTransport.handle_request
    orig_flag = pc._LAYER2_INSTALLED
    pc._LAYER2_INSTALLED = False
    try:
        assert install_transport_guard() is True
        assert install_transport_guard() is False
    finally:
        httpx.AsyncHTTPTransport.handle_async_request = orig_async
        httpx.HTTPTransport.handle_request = orig_sync
        pc._LAYER2_INSTALLED = orig_flag


# ── Layer 3 (socket egress guard) ──────────────────────────────────────────


def test_layer3_socket_guard_install_is_idempotent(monkeypatch):
    import socket
    import tools.gimo_server.services.provider_chokepoint as pc
    from tools.gimo_server.services.provider_chokepoint import install_socket_guard

    orig_connect = socket.socket.connect
    orig_flag = pc._LAYER3_INSTALLED
    pc._LAYER3_INSTALLED = False
    try:
        assert install_socket_guard() is True
        assert install_socket_guard() is False
    finally:
        socket.socket.connect = orig_connect
        pc._LAYER3_INSTALLED = orig_flag
