"""Background worker that processes pending OPS runs.

The worker polls for runs in ``pending`` status and dispatches them
to the active LLM provider for execution.  It respects
``max_concurrent_runs`` from :class:`OpsConfig` and enforces a
per-run timeout.

Lifecycle is managed by the FastAPI lifespan in ``main.py``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .ops_service import OpsService
from .provider_service import ProviderService

logger = logging.getLogger("orchestrator.run_worker")

# How often to poll for pending runs (seconds).
POLL_INTERVAL = 5

# Default per-run timeout if nothing else configured.
DEFAULT_RUN_TIMEOUT = 300  # 5 min


class RunWorker:
    """Async background worker for OPS run execution."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running_ids: set[str] = set()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            logger.info("RunWorker started")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("RunWorker stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("RunWorker tick error")
            await asyncio.sleep(POLL_INTERVAL)

    async def _tick(self) -> None:
        config = OpsService.get_config()
        max_concurrent = config.max_concurrent_runs

        # Clean finished IDs
        self._running_ids = {
            rid for rid in self._running_ids
            if self._is_still_active(rid)
        }

        available_slots = max_concurrent - len(self._running_ids)
        if available_slots <= 0:
            return

        pending = OpsService.list_pending_runs()
        for run in pending[:available_slots]:
            if run.id not in self._running_ids:
                self._running_ids.add(run.id)
                asyncio.create_task(self._execute_run(run.id))

    def _is_still_active(self, run_id: str) -> bool:
        run = OpsService.get_run(run_id)
        return run is not None and run.status in ("pending", "running")

    async def _execute_run(self, run_id: str) -> None:
        try:
            OpsService.update_run_status(run_id, "running", msg="Execution started")

            run = OpsService.get_run(run_id)
            if not run:
                return

            approved = OpsService.get_approved(run.approved_id)
            if not approved:
                OpsService.update_run_status(run_id, "error", msg="Approved entry not found")
                return

            prompt = (
                f"Execute the following approved operation:\n\n"
                f"--- PROMPT ---\n{approved.prompt}\n\n"
                f"--- CONTENT ---\n{approved.content}\n\n"
                f"Provide the execution result."
            )

            try:
                provider_name, result = await asyncio.wait_for(
                    ProviderService.generate(prompt, context={"mode": "execute"}),
                    timeout=DEFAULT_RUN_TIMEOUT,
                )
                OpsService.append_log(run_id, level="INFO", msg=f"Provider: {provider_name}")
                OpsService.append_log(run_id, level="INFO", msg=f"Result:\n{result[:2000]}")
                OpsService.update_run_status(run_id, "done", msg="Execution completed")
            except asyncio.TimeoutError:
                OpsService.update_run_status(run_id, "error", msg="Execution timed out")
            except Exception as exc:
                OpsService.update_run_status(
                    run_id, "error", msg=f"Provider error: {str(exc)[:200]}"
                )
        except Exception:
            logger.exception("Failed to execute run %s", run_id)
            try:
                OpsService.update_run_status(run_id, "error", msg="Internal worker error")
            except Exception:
                pass
        finally:
            self._running_ids.discard(run_id)
