"""Governance subsystem bootstrap (R20-002 / R20-004).

Single source of truth for wiring the governance singletons that must be
available in BOTH the FastAPI process and the MCP-bridge process. Prior
to R20, these were only initialized inside the FastAPI lifespan in
``tools/gimo_server/main.py``, which meant the MCP-bridge process saw
``StorageService._shared_gics is None`` for its entire lifetime and every
store-backed governance read (proof chain, GICS insight, trust, etc.)
silently returned empty data.

Both boot paths MUST call :func:`init_governance_subsystem` at startup.
No governance singleton may be initialized inline outside this helper.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("orchestrator.services.bootstrap")

# Process-level guard so repeat calls (e.g. test suite re-imports) are a no-op.
_INITIALIZED: bool = False
_GICS_SERVICE: Optional[Any] = None


def init_governance_subsystem(*, start_daemon: bool = True) -> Optional[Any]:
    """Initialize the governance subsystem singletons.

    This function is idempotent: after the first successful call it will
    return the cached GICS service without re-initializing anything.

    Callers:
      - ``tools/gimo_server/main.py`` lifespan (FastAPI process)
      - ``tools/gimo_server/mcp_bridge/server.py`` ``_startup_and_run``
        (MCP-bridge process)

    Args:
      start_daemon: if True, starts the GICS daemon + health check. The
        MCP-bridge process may choose False when the FastAPI process is
        already running the daemon on the same machine; in that case the
        bridge reuses the daemon socket transparently via GicsService's
        client.

    Returns:
      The shared ``GicsService`` instance (may be None if initialization
      failed — callers MUST degrade gracefully).
    """
    global _INITIALIZED, _GICS_SERVICE
    if _INITIALIZED:
        return _GICS_SERVICE

    try:
        from .gics_service import GicsService
        from .storage_service import StorageService

        gics = GicsService()
        if start_daemon:
            try:
                gics.start_daemon()
                gics.start_health_check()
            except Exception as exc:
                logger.warning("GICS daemon start failed (degraded mode): %s", exc)

        StorageService.set_shared_gics(gics)
        _GICS_SERVICE = gics
        _INITIALIZED = True
        logger.info(
            "Governance subsystem initialized (gics_alive=%s)",
            getattr(gics, "_last_alive", False),
        )
        return gics
    except Exception as exc:
        logger.error("init_governance_subsystem failed: %s", exc)
        _INITIALIZED = True  # avoid retry storms
        return None


def get_bootstrap_gics() -> Optional[Any]:
    """Return the process-wide GICS reference established by bootstrap."""
    return _GICS_SERVICE


def reset_for_tests() -> None:
    """Reset bootstrap state (tests only)."""
    global _INITIALIZED, _GICS_SERVICE
    _INITIALIZED = False
    _GICS_SERVICE = None
