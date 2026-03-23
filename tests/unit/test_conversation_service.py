from __future__ import annotations

import threading
import time

from tools.gimo_server.models.conversation import GimoItem
from tools.gimo_server.services.conversation_service import ConversationService


def test_append_item_preserves_all_concurrent_writes(tmp_path):
    original_threads_dir = ConversationService.THREADS_DIR
    ConversationService.THREADS_DIR = tmp_path / "threads"
    try:
        thread = ConversationService.create_thread(workspace_root=str(tmp_path), title="race")
        turn = ConversationService.add_turn(thread.id, agent_id="user")
        assert turn is not None

        start = threading.Barrier(3)
        errors: list[str] = []

        def worker(prefix: str):
            try:
                start.wait(timeout=5)
                for idx in range(25):
                    ok = ConversationService.append_item(
                        thread.id,
                        turn.id,
                        GimoItem(type="text", content=f"{prefix}-{idx}", status="completed"),
                    )
                    if not ok:
                        errors.append(f"append failed for {prefix}-{idx}")
            except Exception as exc:  # pragma: no cover - debugging path
                errors.append(repr(exc))

        left = threading.Thread(target=worker, args=("left",))
        right = threading.Thread(target=worker, args=("right",))
        left.start()
        right.start()
        start.wait(timeout=5)
        left.join(timeout=5)
        right.join(timeout=5)

        assert not errors
        stored = ConversationService.get_thread(thread.id)
        assert stored is not None
        items = stored.turns[0].items
        expected = {f"left-{idx}" for idx in range(25)} | {f"right-{idx}" for idx in range(25)}
        assert len(items) == 50
        assert {item.content for item in items} == expected
    finally:
        ConversationService.THREADS_DIR = original_threads_dir


def test_failed_append_item_does_not_bump_updated_at(tmp_path):
    original_threads_dir = ConversationService.THREADS_DIR
    ConversationService.THREADS_DIR = tmp_path / "threads"
    try:
        thread = ConversationService.create_thread(workspace_root=str(tmp_path), title="noop")
        before = ConversationService.get_thread(thread.id)
        assert before is not None
        before_ts = before.updated_at

        time.sleep(0.02)
        ok = ConversationService.append_item(
            thread.id,
            "missing_turn",
            GimoItem(type="text", content="x", status="completed"),
        )

        after = ConversationService.get_thread(thread.id)
        assert ok is False
        assert after is not None
        assert after.updated_at == before_ts
    finally:
        ConversationService.THREADS_DIR = original_threads_dir
