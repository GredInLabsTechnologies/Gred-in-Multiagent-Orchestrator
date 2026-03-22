"""Global Event Emitter for GIMO with circuit breaker and coalescing."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.services.notifications")

CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_COOLDOWN = 30.0
COALESCE_INTERVAL = 0.1  # 100ms


@dataclass
class SubscriberState:
    queue: asyncio.Queue
    consecutive_failures: int = 0
    circuit_open: bool = False
    circuit_opened_at: float = 0.0
    total_drops: int = 0
    total_published: int = 0


class NotificationService:
    """Global Event Emitter with circuit breaker per subscriber and event coalescing."""

    _subscribers: List[SubscriberState] = []
    _queue_maxsize: int = 200
    _metrics: Dict[str, int] = {
        "published": 0,
        "dropped": 0,
        "forced_disconnects": 0,
        "circuit_opens": 0,
        "coalesced": 0,
    }
    _pending: Dict[str, Dict[str, Any]] = {}
    _flush_task: Optional[asyncio.Task] = None

    @classmethod
    def configure(cls, *, queue_maxsize: int | None = None):
        if queue_maxsize is not None:
            cls._queue_maxsize = max(1, int(queue_maxsize))

    @classmethod
    def reset_state_for_tests(cls):
        cls._subscribers = []
        cls._queue_maxsize = 200
        cls._metrics = {
            "published": 0,
            "dropped": 0,
            "forced_disconnects": 0,
            "circuit_opens": 0,
            "coalesced": 0,
        }
        cls._pending = {}
        if cls._flush_task and not cls._flush_task.done():
            cls._flush_task.cancel()
        cls._flush_task = None

    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        return {
            **cls._metrics,
            "subscribers": len(cls._subscribers),
            "queue_maxsize": cls._queue_maxsize,
            "pending_coalesce": len(cls._pending),
        }

    @classmethod
    async def subscribe(cls) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=cls._queue_maxsize)
        state = SubscriberState(queue=queue)
        cls._subscribers.append(state)
        logger.info("New SSE client connected. Total: %d", len(cls._subscribers))
        cls._ensure_flush_task()
        return queue

    @classmethod
    def unsubscribe(cls, queue: asyncio.Queue):
        cls._subscribers = [s for s in cls._subscribers if s.queue is not queue]
        logger.info("SSE client disconnected. Total: %d", len(cls._subscribers))

    @classmethod
    async def publish(cls, event_type: str, payload: Dict[str, Any]):
        if not cls._subscribers:
            return

        is_critical = payload.get("critical", False) or event_type in (
            "system_degraded", "action_requires_approval", "security_alert",
            "child_run_completed", "all_children_completed",
        )

        if is_critical:
            await cls._broadcast_now(event_type, payload)
        else:
            coalesce_key = f"{payload.get('run_id', '_')}:{event_type}"
            cls._pending[coalesce_key] = {"event": event_type, "data": payload}
            cls._metrics["coalesced"] += 1

    @classmethod
    async def _broadcast_now(cls, event_type: str, payload: Dict[str, Any]):
        message = json.dumps({"event": event_type, "data": payload})
        stale: List[SubscriberState] = []

        for sub in list(cls._subscribers):
            if sub.circuit_open:
                elapsed = time.monotonic() - sub.circuit_opened_at
                if elapsed < CIRCUIT_BREAKER_COOLDOWN:
                    continue
                # Half-open: try one message
                sub.circuit_open = False

            try:
                sub.queue.put_nowait(message)
                sub.consecutive_failures = 0
                sub.total_published += 1
                cls._metrics["published"] += 1
            except asyncio.QueueFull:
                sub.consecutive_failures += 1
                sub.total_drops += 1
                cls._metrics["dropped"] += 1

                if sub.consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                    sub.circuit_open = True
                    sub.circuit_opened_at = time.monotonic()
                    cls._metrics["circuit_opens"] += 1
                    logger.warning(
                        "Circuit breaker opened for subscriber (drops=%d)",
                        sub.total_drops,
                    )
                else:
                    # Coalescing: drop oldest, push newest
                    try:
                        sub.queue.get_nowait()
                        sub.queue.put_nowait(message)
                        sub.total_published += 1
                        cls._metrics["published"] += 1
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        stale.append(sub)
                        cls._metrics["forced_disconnects"] += 1
            except Exception as e:
                logger.error("Error publishing to SSE subscriber: %s", e)

        for sub in stale:
            cls.unsubscribe(sub.queue)

    @classmethod
    def _ensure_flush_task(cls):
        if cls._flush_task is None or cls._flush_task.done():
            try:
                cls._flush_task = asyncio.create_task(cls._flush_loop())
            except RuntimeError:
                pass

    @classmethod
    async def _flush_loop(cls):
        while cls._subscribers:
            await asyncio.sleep(COALESCE_INTERVAL)
            if cls._pending:
                batch = dict(cls._pending)
                cls._pending.clear()
                for entry in batch.values():
                    await cls._broadcast_now(entry["event"], entry["data"])
        cls._flush_task = None
