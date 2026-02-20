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

    @classmethod
    async def subscribe(cls) -> asyncio.Queue:
        """Create a new subscription queue for an SSE client."""
        queue = asyncio.Queue()
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
        
        # We fire and forget to all queues
        for queue in cls._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("SSE subscriber queue is full. Dropping message.")
            except Exception as e:
                logger.error(f"Error publishing to SSE subscriber: {e}")
