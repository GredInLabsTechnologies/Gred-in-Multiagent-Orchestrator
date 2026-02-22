import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .notification_service import NotificationService
from ..config import OPS_DATA_DIR
from ..ops_models import GimoItem, GimoThread, GimoTurn

logger = logging.getLogger("orchestrator.services.conversation")

class ConversationService:
    """Service for managing GIMO conversation threads, turns, and items."""

    THREADS_DIR: Path = OPS_DATA_DIR / "threads"

    @classmethod
    def _ensure_dir(cls):
        cls.THREADS_DIR.mkdir(parents=True, exist_ok=True)

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
        path = cls.THREADS_DIR / f"{thread_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return GimoThread.model_validate(data)
        except Exception as e:
            logger.error(f"Error loading thread {thread_id}: {e}")
            return None

    @classmethod
    def create_thread(cls, workspace_root: str, title: str = "New Conversation") -> GimoThread:
        cls._ensure_dir()
        thread = GimoThread(
            workspace_root=workspace_root,
            title=title
        )
        cls.save_thread(thread)
        return thread

    @classmethod
    def save_thread(cls, thread: GimoThread):
        cls._ensure_dir()
        thread.updated_at = datetime.now(timezone.utc)
        path = cls.THREADS_DIR / f"{thread.id}.json"
        path.write_text(thread.model_dump_json(indent=2), encoding="utf-8")
        
        # Broadcast update for the whole thread
        asyncio.create_task(NotificationService.publish("thread_updated", thread.model_dump()))

    @classmethod
    def add_turn(cls, thread_id: str, agent_id: str) -> Optional[GimoTurn]:
        thread = cls.get_thread(thread_id)
        if not thread:
            return None
        
        turn = GimoTurn(agent_id=agent_id)
        thread.turns.append(turn)
        cls.save_thread(thread)
        return turn

    @classmethod
    def append_item(cls, thread_id: str, turn_id: str, item: GimoItem) -> bool:
        thread = cls.get_thread(thread_id)
        if not thread:
            return False
        
        turn = cls._find_turn(thread, turn_id)
        if turn:
            turn.items.append(item)
            cls.save_thread(thread)
            
            # Broadcast item creation
            asyncio.create_task(NotificationService.publish("item_created", {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "item": item.model_dump()
            }))
            return True
        return False

    @classmethod
    def update_item_content(cls, thread_id: str, turn_id: str, item_id: str, delta: str, status: Optional[str] = None) -> bool:
        thread = cls.get_thread(thread_id)
        if not thread:
            return False
        
        item = cls._find_item(thread, turn_id, item_id)
        if item:
            item.content += delta
            if status:
                item.status = status
            cls.save_thread(thread)
            
            # Focused broadcast for the specific item update
            asyncio.create_task(NotificationService.publish("item_delta", {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "item_id": item_id,
                "delta": delta,
                "status": item.status
            }))
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
