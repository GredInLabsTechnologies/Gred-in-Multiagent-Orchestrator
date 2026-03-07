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

    asyncio.run(NotificationService.publish("event", {"seq": 1}))
    asyncio.run(NotificationService.publish("event", {"seq": 2}))
    asyncio.run(NotificationService.publish("event", {"seq": 3}))

    first = json.loads(queue.get_nowait())
    second = json.loads(queue.get_nowait())

    assert first["data"]["seq"] == 2
    assert second["data"]["seq"] == 3

    metrics = NotificationService.get_metrics()
    assert metrics["dropped"] == 1
    assert metrics["forced_disconnects"] == 0


def test_publish_disconnects_permanently_saturated_subscriber(monkeypatch):
    NotificationService.configure(queue_maxsize=1)
    queue = asyncio.run(NotificationService.subscribe())

    state = {"count": 0}
    original_put_nowait = queue.put_nowait

    def _saturated_put_nowait(item):
        state["count"] += 1
        if state["count"] >= 2:
            raise asyncio.QueueFull
        return original_put_nowait(item)

    monkeypatch.setattr(queue, "put_nowait", _saturated_put_nowait)

    asyncio.run(NotificationService.publish("event", {"seq": 1}))
    asyncio.run(NotificationService.publish("event", {"seq": 2}))

    metrics = NotificationService.get_metrics()
    assert metrics["forced_disconnects"] == 1
    assert metrics["subscribers"] == 0
