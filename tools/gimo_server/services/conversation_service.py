import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional, TypeVar

from .notification_service import NotificationService
from ..config import OPS_DATA_DIR
from ..ops_models import GimoItem, GimoThread, GimoTurn
from .workspace_policy_service import WorkspacePolicyService

logger = logging.getLogger("orchestrator.services.conversation")
_MutationResultT = TypeVar("_MutationResultT")

class ConversationService:
    """Service for managing GIMO conversation threads, turns, and items.
    
    **Authority of threads.**
    """

    THREADS_DIR: Path = OPS_DATA_DIR / "threads"
    _ALLOWED_TURN_AGENT_IDS = frozenset({"user", "User", "system", "orchestrator"})
    _locks_guard = threading.Lock()
    _thread_locks: dict[str, threading.RLock] = {}

    @classmethod
    def _ensure_dir(cls):
        cls.THREADS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _get_thread_lock(cls, thread_id: str) -> threading.RLock:
        with cls._locks_guard:
            lock = cls._thread_locks.get(thread_id)
            if lock is None:
                lock = threading.RLock()
                cls._thread_locks[thread_id] = lock
            return lock

    @classmethod
    def _thread_path(cls, thread_id: str) -> Path:
        return cls.THREADS_DIR / f"{thread_id}.json"

    @staticmethod
    def _schedule_notification(coro: Any) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                coro.close()
            except Exception:
                pass
            return
        asyncio.create_task(coro)

    @classmethod
    def _load_thread_unlocked(cls, thread_id: str) -> Optional[GimoThread]:
        path = cls._thread_path(thread_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            thread = GimoThread.model_validate(data)
            thread._legacy_missing_agent_preset = not bool(str(data.get("agent_preset") or "").strip())
            return thread
        except Exception as e:
            logger.error(f"Error loading thread {thread_id}: {e}")
            return None

    @classmethod
    def _write_thread_unlocked(cls, thread: GimoThread) -> None:
        cls._ensure_dir()
        thread.updated_at = datetime.now(timezone.utc)
        path = cls._thread_path(thread.id)
        tmp_path = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
        try:
            tmp_path.write_text(thread.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    @classmethod
    def _publish_thread_updated(cls, thread: GimoThread) -> None:
        cls._schedule_notification(NotificationService.publish("thread_updated", thread.model_dump()))

    @classmethod
    def mutate_thread(
        cls,
        thread_id: str,
        mutator: Callable[[GimoThread], _MutationResultT],
    ) -> Optional[_MutationResultT]:
        lock = cls._get_thread_lock(thread_id)
        should_publish = False
        with lock:
            thread = cls._load_thread_unlocked(thread_id)
            if not thread:
                return None
            original_dump = thread.model_dump(mode="json")
            result = mutator(thread)
            if result is False:
                return result
            if thread.model_dump(mode="json") == original_dump:
                return result
            cls._write_thread_unlocked(thread)
            should_publish = True
        if should_publish:
            cls._publish_thread_updated(thread)
        return result

    @classmethod
    def list_threads(cls, workspace_root: Optional[str] = None) -> List[GimoThread]:
        cls._ensure_dir()
        threads = []
        for p in cls.THREADS_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                thread = GimoThread.model_validate(data)
                if workspace_root and thread.workspace_root != workspace_root:
                    continue
                threads.append(thread)
            except Exception as e:
                logger.error(f"Error loading thread {p.name}: {e}")
        
        # Sort by updated_at descending
        return sorted(threads, key=lambda t: t.updated_at, reverse=True)

    @classmethod
    def get_thread(cls, thread_id: str) -> Optional[GimoThread]:
        return cls._load_thread_unlocked(thread_id)

    @classmethod
    def create_thread(cls, workspace_root: str, title: str = "New Conversation") -> GimoThread:
        cls._ensure_dir()
        thread = GimoThread(
            workspace_root=workspace_root,
            title=title,
            metadata=WorkspacePolicyService.default_metadata_for_surface(
                WorkspacePolicyService.SURFACE_OPERATOR
            ),
        )
        cls.save_thread(thread)
        return thread

    @classmethod
    def save_thread(cls, thread: GimoThread):
        lock = cls._get_thread_lock(thread.id)
        with lock:
            cls._write_thread_unlocked(thread)
        cls._publish_thread_updated(thread)

    @classmethod
    def _validate_turn_agent_id(cls, agent_id: str) -> str:
        normalized = str(agent_id or "").strip()
        if not normalized:
            raise ValueError("agent_id is required")
        if normalized not in cls._ALLOWED_TURN_AGENT_IDS:
            allowed = ", ".join(sorted(cls._ALLOWED_TURN_AGENT_IDS))
            raise ValueError(
                f"Unsupported thread agent_id '{normalized}'. Allowed values: {allowed}"
            )
        return normalized

    @classmethod
    def add_turn(cls, thread_id: str, agent_id: str) -> Optional[GimoTurn]:
        validated_agent_id = cls._validate_turn_agent_id(agent_id)

        def _mutate(thread: GimoThread) -> GimoTurn:
            turn = GimoTurn(agent_id=validated_agent_id)
            thread.turns.append(turn)
            return turn

        return cls.mutate_thread(thread_id, _mutate)

    @classmethod
    def append_item(cls, thread_id: str, turn_id: str, item: GimoItem) -> bool:
        def _mutate(thread: GimoThread) -> bool:
            turn = cls._find_turn(thread, turn_id)
            if not turn:
                return False
            turn.items.append(item)
            return True

        success = cls.mutate_thread(thread_id, _mutate)
        if success:
            cls._schedule_notification(NotificationService.publish("item_created", {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "item": item.model_dump()
            }))
            return True
        return False

    @classmethod
    def update_item_content(cls, thread_id: str, turn_id: str, item_id: str, delta: str, status: Optional[str] = None) -> bool:
        event_payload: dict[str, Any] = {}

        def _mutate(thread: GimoThread) -> bool:
            item = cls._find_item(thread, turn_id, item_id)
            if not item:
                return False
            item.content += delta
            if status:
                item.status = status
            event_payload.update({
                "thread_id": thread_id,
                "turn_id": turn_id,
                "item_id": item_id,
                "delta": delta,
                "status": item.status,
            })
            return True

        success = cls.mutate_thread(thread_id, _mutate)
        if success:
            cls._schedule_notification(NotificationService.publish("item_delta", event_payload))
            return True
        return False

    @staticmethod
    def _find_turn(thread: GimoThread, turn_id: str) -> Optional[GimoTurn]:
        for turn in thread.turns:
            if turn.id == turn_id:
                return turn
        return None

    @staticmethod
    def _find_item(thread: GimoThread, turn_id: str, item_id: str) -> Optional[GimoItem]:
        for turn in thread.turns:
            if turn.id == turn_id:
                for item in turn.items:
                    if item.id == item_id:
                        return item
        return None

    @classmethod
    def fork_thread(cls, thread_id: str, turn_id: str, new_title: Optional[str] = None) -> Optional[GimoThread]:
        source = cls.get_thread(thread_id)
        if not source:
            return None
        
        new_turns = cls._extract_turns_up_to(source, turn_id)
        if not new_turns:
            return None
            
        new_thread = GimoThread(
            workspace_root=source.workspace_root,
            title=new_title or f"Fork of {source.title}",
            turns=new_turns,
            metadata={"forked_from": thread_id, "forked_at_turn": turn_id}
        )
        cls.save_thread(new_thread)
        return new_thread

    @staticmethod
    def _extract_turns_up_to(thread: GimoThread, turn_id: str) -> List[GimoTurn]:
        """Helper to extract a slice of turns for forking."""
        subset = []
        for turn in thread.turns:
            subset.append(turn)
            if turn.id == turn_id:
                return subset
        return []
