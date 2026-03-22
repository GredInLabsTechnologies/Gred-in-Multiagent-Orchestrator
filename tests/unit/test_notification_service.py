import asyncio
import json

import pytest

from tools.gimo_server.services.notification_service import NotificationService


@pytest.fixture(autouse=True)
def _reset_notification_state():
    NotificationService.reset_state_for_tests()
    yield
    NotificationService.reset_state_for_tests()


def test_subscribe_uses_bounded_queue():
    NotificationService.configure(queue_maxsize=3)

    queue = asyncio.run(NotificationService.subscribe())

    assert queue.maxsize == 3


def test_publish_coalesces_when_subscriber_queue_is_full():
    NotificationService.configure(queue_maxsize=2)
    queue = asyncio.run(NotificationService.subscribe())

    # Use critical=True so messages go through _broadcast_now (not deferred coalescing)
    asyncio.run(NotificationService.publish("event", {"seq": 1, "critical": True}))
    asyncio.run(NotificationService.publish("event", {"seq": 2, "critical": True}))
    asyncio.run(NotificationService.publish("event", {"seq": 3, "critical": True}))

    # Queue maxsize=2: seq=1 fills slot 1, seq=2 fills slot 2 (full),
    # seq=3 triggers QueueFull → coalescing drops oldest (seq=1), pushes seq=3
    first = json.loads(queue.get_nowait())
    second = json.loads(queue.get_nowait())

    assert first["data"]["seq"] == 2
    assert second["data"]["seq"] == 3

    metrics = NotificationService.get_metrics()
    assert metrics["dropped"] == 1
    assert metrics["forced_disconnects"] == 0


def test_publish_disconnects_permanently_saturated_subscriber():
    """After CIRCUIT_BREAKER_THRESHOLD (5) consecutive QueueFull, subscriber is disconnected."""
    NotificationService.configure(queue_maxsize=1)
    queue = asyncio.run(NotificationService.subscribe())

    # Fill the queue first
    asyncio.run(NotificationService.publish("event", {"seq": 0, "critical": True}))

    # Now send enough critical messages to trigger circuit breaker (threshold=5)
    # Each will hit QueueFull → coalescing (drop oldest, push new) → 1 failure each
    # After 5 consecutive failures the circuit breaker opens
    for i in range(1, 7):
        asyncio.run(NotificationService.publish("event", {"seq": i, "critical": True}))

    metrics = NotificationService.get_metrics()
    assert metrics["circuit_opens"] >= 1
