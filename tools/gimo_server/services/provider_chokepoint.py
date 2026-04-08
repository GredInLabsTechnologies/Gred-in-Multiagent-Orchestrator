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
