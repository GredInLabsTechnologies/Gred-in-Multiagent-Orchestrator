import asyncio
import json
import logging
from typing import Any, Dict

logger = logging.getLogger("orchestrator.services.notifications")

class NotificationService:
    """
    Global Event Emitter for GIMO.
    Allows internal services (like GraphEngine) to publish events that are 
    then broadcasted to connected SSE clients (e.g., Master Orchestrators).
    """
    _subscribers = []
    _queue_maxsize = 200
    _metrics = {
        "published": 0,
        "dropped": 0,
        "forced_disconnects": 0,
    }

    @classmethod
    def configure(cls, *, queue_maxsize: int | None = None):
        """Runtime configuration for notification flow control."""
        if queue_maxsize is not None:
            cls._queue_maxsize = max(1, int(queue_maxsize))

    @classmethod
    def reset_state_for_tests(cls):
        """Testing helper to ensure state isolation across test cases."""
        cls._subscribers = []
        cls._queue_maxsize = 200
        cls._metrics = {
            "published": 0,
            "dropped": 0,
            "forced_disconnects": 0,
        }

    @classmethod
    def get_metrics(cls) -> Dict[str, int]:
        """Return snapshot of notification delivery metrics."""
        return {
            **cls._metrics,
            "subscribers": len(cls._subscribers),
            "queue_maxsize": cls._queue_maxsize,
        }

    @classmethod
    async def subscribe(cls) -> asyncio.Queue:
        """Create a new subscription queue for an SSE client."""
        queue = asyncio.Queue(maxsize=cls._queue_maxsize)
        cls._subscribers.append(queue)
        logger.info(f"New SSE client connected. Total: {len(cls._subscribers)}")
        return queue

    @classmethod
    def unsubscribe(cls, queue: asyncio.Queue):
        """Remove a subscription queue."""
        if queue in cls._subscribers:
            cls._subscribers.remove(queue)
            logger.info(f"SSE client disconnected. Total: {len(cls._subscribers)}")

    @classmethod
    async def publish(cls, event_type: str, payload: Dict[str, Any]):
        """Publish an event to all connected SSE clients."""
        if not cls._subscribers:
            return

        message = json.dumps({
            "event": event_type,
            "data": payload
        })

        # We fire and forget to all queues with bounded backpressure.
        stale_subscribers = []
        for queue in list(cls._subscribers):
            try:
                queue.put_nowait(message)
                cls._metrics["published"] += 1
            except asyncio.QueueFull:
                cls._metrics["dropped"] += 1
                # Coalescing policy: when queue is saturated, drop oldest to keep stream current.
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                    cls._metrics["published"] += 1
                    logger.warning("SSE subscriber queue full; dropped oldest message to publish newest event.")
                except asyncio.QueueEmpty:
                    logger.warning("SSE subscriber queue full and empty on drain attempt; dropping message.")
                except asyncio.QueueFull:
                    stale_subscribers.append(queue)
                    cls._metrics["forced_disconnects"] += 1
                    logger.warning("SSE subscriber remained saturated; disconnecting subscriber.")
            except Exception as e:
                logger.error(f"Error publishing to SSE subscriber: {e}")

        for queue in stale_subscribers:
            cls.unsubscribe(queue)
