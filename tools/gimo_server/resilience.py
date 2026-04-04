"""Resilience kernel — composable primitives for task supervision, auth
throttling, and dependency enforcement.

Three primitives, zero external dependencies:

* ``SupervisedTask``   – wraps ``asyncio.create_task`` with lifecycle
  callbacks, timeout, and health reporting.  Solves fire-and-forget lost
  exceptions and stuck-run problems.
* ``AuthThrottle``     – sliding-window rate limiter purpose-built for
  pre-auth endpoints.  Standalone (does not depend on ``check_rate_limit``
  or ``verify_token``).
* ``require_gics``     – fails hard when GICS is ``None`` instead of
  silently no-oping.  One call replaces every ``if not self.gics: return``
  guard with an auditable contract.

Design notes (aligned with AGENTS.md doctrine):
- Zero new dependencies.
- Each primitive is < 40 lines.
- Composable: they work independently or together.
- Fail-closed: no silent degradation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, Optional, Set

logger = logging.getLogger("orchestrator.resilience")


# ---------------------------------------------------------------------------
# 1. SupervisedTask — lifecycle-aware async task wrapper
# ---------------------------------------------------------------------------
class SupervisedTask:
    """Registry of supervised background tasks with failure callbacks.

    Usage::

        supervisor = SupervisedTask()

        async def on_fail(run_id, exc):
            OpsService.update_run_status(run_id, "error", msg=str(exc)[:200])

        supervisor.spawn(
            coro=EngineService.execute_run(run_id),
            name=f"run:{run_id}",
            on_failure=lambda exc: on_fail(run_id, exc),
            timeout=3600,
        )

        # At shutdown:
        await supervisor.shutdown()
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task[Any]] = {}

    def spawn(
        self,
        coro: Awaitable[Any],
        *,
        name: str,
        on_failure: Optional[Callable[[Exception], Awaitable[None]]] = None,
        timeout: Optional[float] = None,
    ) -> asyncio.Task[Any]:
        """Create a supervised task.  Exceptions invoke *on_failure* instead
        of being silently lost."""

        async def _supervised() -> Any:
            try:
                if timeout:
                    return await asyncio.wait_for(coro, timeout=timeout)
                return await coro
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Supervised task %s failed: %s", name, exc)
                if on_failure:
                    try:
                        await on_failure(exc)
                    except Exception as cb_err:
                        logger.error("on_failure callback for %s raised: %s", name, cb_err)
                raise

        task = asyncio.create_task(_supervised(), name=name)
        self._tasks[name] = task
        task.add_done_callback(lambda t: self._tasks.pop(t.get_name(), None))
        return task

    @property
    def active(self) -> Set[str]:
        return {n for n, t in self._tasks.items() if not t.done()}

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Cancel all running tasks and wait for graceful exit."""
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.wait(
                list(self._tasks.values()), timeout=timeout,
            )
        self._tasks.clear()


# ---------------------------------------------------------------------------
# 2. AuthThrottle — pre-auth sliding-window rate limiter
# ---------------------------------------------------------------------------
class AuthThrottle:
    """Lightweight per-IP sliding-window limiter for auth endpoints.

    Does NOT depend on ``verify_token`` (runs before auth).  Tracks
    failures separately and applies exponential backoff on repeated
    bad attempts.

    Usage::

        auth_throttle = AuthThrottle(max_attempts=10, window_seconds=60)

        # In FastAPI endpoint:
        auth_throttle.check(request)          # raises 429 if over limit
        auth_throttle.record_failure(request)  # after bad login
    """

    def __init__(self, *, max_attempts: int = 10, window_seconds: int = 60) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: Dict[str, list[float]] = defaultdict(list)
        self._failures: Dict[str, int] = defaultdict(int)

    def _client_ip(self, request: Any) -> str:
        return request.client.host if getattr(request, "client", None) else "unknown"

    def _prune(self, ip: str) -> None:
        cutoff = time.monotonic() - self.window
        self._hits[ip] = [t for t in self._hits[ip] if t > cutoff]

    def check(self, request: Any) -> None:
        """Raise HTTPException(429) if the IP exceeds the rate limit."""
        from fastapi import HTTPException

        ip = self._client_ip(request)
        self._prune(ip)

        # Exponential penalty: halve the limit for every 3 consecutive failures
        effective_limit = max(
            2, self.max_attempts >> (self._failures[ip] // 3)
        )
        if len(self._hits[ip]) >= effective_limit:
            logger.warning("Auth throttle: IP %s blocked (%d hits, %d failures)", ip, len(self._hits[ip]), self._failures[ip])
            raise HTTPException(status_code=429, detail="Too many authentication attempts")
        self._hits[ip].append(time.monotonic())

    def record_failure(self, request: Any) -> None:
        ip = self._client_ip(request)
        self._failures[ip] = self._failures.get(ip, 0) + 1

    def reset(self, request: Any) -> None:
        """Reset failure counter on successful login."""
        ip = self._client_ip(request)
        self._failures.pop(ip, None)


# ---------------------------------------------------------------------------
# 3. require_gics — dependency enforcement
# ---------------------------------------------------------------------------
class GicsUnavailableError(RuntimeError):
    """Raised when a storage operation requires GICS but it is None."""


def require_gics(gics: Any, operation: str = "storage") -> Any:
    """Return *gics* if truthy, otherwise raise ``GicsUnavailableError``.

    Replaces every ``if not self.gics: return`` guard with a single
    auditable contract.  Calling code becomes::

        gics = require_gics(self.gics, "save_cost_event")
        gics.put(key, data)

    For operations where no-op is acceptable (e.g. non-critical telemetry),
    keep the existing guard — this helper is for paths where silent data
    loss is unacceptable.
    """
    if gics:
        return gics
    raise GicsUnavailableError(
        f"GICS is not initialized — cannot perform {operation}. "
        "Ensure GICS daemon is running and StorageService received a valid instance."
    )
