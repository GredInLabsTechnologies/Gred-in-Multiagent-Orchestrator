"""R18 Change 2 — provider_invoke chokepoint (Layer 1: explicit wrapper).

Single in-process entry point through which every provider call MUST pass.
The chokepoint uses a ``ContextVar`` to track in-flight invocations and a
module-level counter to expose a tamper-evident invocation log to the
governance gateway (and tests).

Full R18 v2.2 Change 2 calls for three layers:
  1. **Explicit wrapper** (this module) — adapters call ``provider_invoke``.
  2. **httpx/SDK monkey-patch** — transport-level guard (deferred).
  3. **Socket egress denylist** — last-line defense (deferred).

Layers 2 and 3 are documented as follow-up in the implementation report;
this module delivers Layer 1 so every future adapter has a canonical
chokepoint to wire into, and the SAGP gateway has a single place to hook.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("gimo.provider_chokepoint")

# In-flight guard: detects recursive/uncontrolled provider calls.
_IN_FLIGHT: ContextVar[Optional[str]] = ContextVar("gimo_provider_in_flight", default=None)

# Tamper-evident invocation counter (per-process, used by tests + telemetry).
_INVOCATION_COUNT: int = 0
_LAST_PROVIDER: Optional[str] = None


@dataclass
class InvocationRecord:
    provider: str
    model: str
    kind: str  # "generate" | "chat_with_tools"
    metadata: dict = field(default_factory=dict)


class ProviderChokepointError(RuntimeError):
    """Raised when the chokepoint is bypassed or used incorrectly."""


async def provider_invoke(
    record: InvocationRecord,
    call: Callable[[], Awaitable[Any]],
) -> Any:
    """Single entry point for every provider call.

    Any adapter implementing ``ProviderAdapter.generate`` or
    ``chat_with_tools`` should funnel its actual network call through this
    helper. Future SAGP hooks (pre/post policy, cost, trust) attach here.
    """
    global _INVOCATION_COUNT, _LAST_PROVIDER

    existing = _IN_FLIGHT.get()
    if existing is not None:
        logger.warning(
            "provider_invoke: nested call detected (outer=%s inner=%s/%s)",
            existing, record.provider, record.model,
        )

    token = _IN_FLIGHT.set(f"{record.provider}/{record.model}")
    _INVOCATION_COUNT += 1
    _LAST_PROVIDER = record.provider
    try:
        return await call()
    finally:
        _IN_FLIGHT.reset(token)


def get_invocation_count() -> int:
    """Tamper-evident counter — used by tests and /ops/health/info extensions."""
    return _INVOCATION_COUNT


def get_last_provider() -> Optional[str]:
    return _LAST_PROVIDER


def reset_for_tests() -> None:
    global _INVOCATION_COUNT, _LAST_PROVIDER
    _INVOCATION_COUNT = 0
    _LAST_PROVIDER = None


# ─────────────────────────────────────────────────────────────────────────────
# R18 Change 2 — Layer 2: httpx transport guard
# ─────────────────────────────────────────────────────────────────────────────

# Host suffixes considered "provider egress". Any HTTP request to one of these
# hosts MUST happen inside a ``provider_invoke`` context; otherwise the
# governance spine (policy/trust/cost/proof) never fires.
PROVIDER_HOST_SUFFIXES: tuple[str, ...] = (
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "api.mistral.ai",
    "api.groq.com",
    "api.together.xyz",
    "api.deepseek.com",
    "openrouter.ai",
)

_LAYER2_INSTALLED = False
_LAYER3_INSTALLED = False
_BYPASS_LOG: list[dict[str, Any]] = []


def _is_provider_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.lower()
    return any(host == s or host.endswith("." + s) or host.endswith(s) for s in PROVIDER_HOST_SUFFIXES)


def install_transport_guard(strict: bool = False) -> bool:
    """Layer 2 — wrap httpx transports so egress to provider hosts outside a
    ``provider_invoke`` context is logged (and optionally blocked in strict
    mode). Idempotent. Returns True on first install, False if already active.
    """
    global _LAYER2_INSTALLED
    if _LAYER2_INSTALLED:
        return False
    try:
        import httpx  # type: ignore
    except Exception:
        return False

    orig_async = httpx.AsyncHTTPTransport.handle_async_request  # type: ignore[attr-defined]
    orig_sync = httpx.HTTPTransport.handle_request  # type: ignore[attr-defined]

    def _check(request: Any) -> None:
        try:
            host = request.url.host
        except Exception:
            return
        if not _is_provider_host(host):
            return
        if _IN_FLIGHT.get() is None:
            event = {"host": host, "url": str(request.url), "kind": "layer2"}
            _BYPASS_LOG.append(event)
            logger.warning("provider_chokepoint Layer 2: egress to %s outside provider_invoke", host)
            if strict:
                raise ProviderChokepointError(
                    f"provider_chokepoint: egress to {host} outside provider_invoke context"
                )

    async def _guarded_async(self, request):  # type: ignore[no-untyped-def]
        _check(request)
        return await orig_async(self, request)

    def _guarded_sync(self, request):  # type: ignore[no-untyped-def]
        _check(request)
        return orig_sync(self, request)

    httpx.AsyncHTTPTransport.handle_async_request = _guarded_async  # type: ignore[assignment]
    httpx.HTTPTransport.handle_request = _guarded_sync  # type: ignore[assignment]
    _LAYER2_INSTALLED = True
    logger.info("provider_chokepoint Layer 2 (httpx transport guard) installed (strict=%s)", strict)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# R18 Change 2 — Layer 3: socket egress denylist
# ─────────────────────────────────────────────────────────────────────────────

def install_socket_guard(strict: bool = False) -> bool:
    """Layer 3 — last-line defense: wrap ``socket.socket.connect`` so that
    connections to provider hosts outside a ``provider_invoke`` context are
    logged (and blocked in strict mode). Works even for non-httpx clients.
    Idempotent. Uses DNS name resolution hints via ``socket.getnameinfo``
    best-effort; if resolution fails, the check is skipped.
    """
    global _LAYER3_INSTALLED
    if _LAYER3_INSTALLED:
        return False
    import socket

    orig_connect = socket.socket.connect

    # Keep a small resolved-IP→host cache to avoid reverse-DNS per-connect.
    _host_cache: dict[str, str] = {}

    def _resolve_from_getaddrinfo(ip: str) -> str | None:
        if ip in _host_cache:
            return _host_cache[ip]
        try:
            name, _ = socket.getnameinfo((ip, 0), 0)
            _host_cache[ip] = name
            return name
        except Exception:
            return None

    def _guarded_connect(self, address):  # type: ignore[no-untyped-def]
        try:
            ip = address[0] if isinstance(address, tuple) else None
            host = _resolve_from_getaddrinfo(ip) if ip else None
            if host and _is_provider_host(host) and _IN_FLIGHT.get() is None:
                event = {"host": host, "ip": ip, "kind": "layer3"}
                _BYPASS_LOG.append(event)
                logger.warning(
                    "provider_chokepoint Layer 3: socket egress to %s (%s) outside provider_invoke",
                    host, ip,
                )
                if strict:
                    raise ProviderChokepointError(
                        f"provider_chokepoint: socket egress to {host} outside provider_invoke"
                    )
        except ProviderChokepointError:
            raise
        except Exception:
            pass
        return orig_connect(self, address)

    socket.socket.connect = _guarded_connect  # type: ignore[assignment]
    _LAYER3_INSTALLED = True
    logger.info("provider_chokepoint Layer 3 (socket egress guard) installed (strict=%s)", strict)
    return True


def get_bypass_log() -> list[dict[str, Any]]:
    """Return the list of observed chokepoint bypasses (Layer 2/3 events)."""
    return list(_BYPASS_LOG)


def install_all_layers(strict: bool = False) -> dict[str, bool]:
    return {
        "layer2": install_transport_guard(strict=strict),
        "layer3": install_socket_guard(strict=strict),
    }
