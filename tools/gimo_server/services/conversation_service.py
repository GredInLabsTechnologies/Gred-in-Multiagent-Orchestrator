import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional, TypeVar, get_args

from ..models.agent_routing import ProfileSummary, WorkflowPhase
from ..security.safe_log import sanitize_for_log
from .notification_service import NotificationService
from ..config import OPS_DATA_DIR
from ..ops_models import GimoItem, GimoThread, GimoTurn
from .agent_catalog_service import AgentCatalogService
from .execution.execution_policy_service import ExecutionPolicyService
from .task_descriptor_service import TaskDescriptorService
from .workspace.workspace_policy_service import WorkspacePolicyService

logger = logging.getLogger("orchestrator.services.conversation")
_MutationResultT = TypeVar("_MutationResultT")
_WORKFLOW_PHASE_VALUES = frozenset(str(value) for value in get_args(WorkflowPhase))

class ConversationService:
    """Service for managing GIMO conversation threads, turns, and items.

    **Authority of threads.**
    """

    THREADS_DIR: Path = OPS_DATA_DIR / "threads"
    _AGENT_ID_RE = __import__("re").compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    _locks_guard = threading.Lock()
    _thread_locks: dict[str, threading.RLock] = {}
    # Strong refs for fire-and-forget notification tasks (prevents premature GC).
    _notification_tasks: set[asyncio.Task] = set()

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
    def _canonicalize_proposed_plan(proposed_plan: Any) -> Any:
        if not isinstance(proposed_plan, dict):
            return proposed_plan
        try:
            return TaskDescriptorService.canonicalize_plan_data(proposed_plan)
        except Exception:
            logger.warning("Unable to canonicalize proposed_plan during thread hydration", exc_info=True)
            return proposed_plan

    @staticmethod
    def _derive_workflow_phase(
        raw_phase: Any,
        *,
        proposed_plan: Any,
        metadata: dict[str, Any],
    ) -> WorkflowPhase:
        candidate = str(raw_phase or "").strip()
        if candidate not in _WORKFLOW_PHASE_VALUES:
            candidate = "intake"
        if candidate == "intake" and isinstance(proposed_plan, dict) and proposed_plan:
            if metadata.get("plan_approved") is True:
                return "executing"
            return "awaiting_approval"
        return candidate  # type: ignore[return-value]

    @staticmethod
    def _derive_profile_summary(
        *,
        agent_preset: str | None,
        legacy_mood: str | None,
        workflow_phase: WorkflowPhase,
        metadata: dict[str, Any],
    ) -> ProfileSummary:
        try:
            profile = AgentCatalogService.resolve_profile(
                agent_preset=agent_preset,
                legacy_mood=None if agent_preset else legacy_mood,
                workflow_phase=workflow_phase,
            )
        except KeyError:
            fallback_preset: str | None = None
            if legacy_mood:
                try:
                    fallback_preset = AgentCatalogService.resolve_preset_name(legacy_mood=legacy_mood)
                except KeyError:
                    fallback_preset = None
            profile = AgentCatalogService.resolve_profile(
                agent_preset=fallback_preset or "plan_orchestrator",
                workflow_phase=workflow_phase,
            )

        explicit_policy_raw = metadata.get("execution_policy")
        if isinstance(explicit_policy_raw, str) and explicit_policy_raw.strip():
            try:
                explicit_policy = ExecutionPolicyService.canonical_policy_name(explicit_policy_raw.strip())
                profile = profile.model_copy(update={"execution_policy": explicit_policy})
            except KeyError:
                logger.warning(
                    "Invalid execution policy '%s' on thread summary; keeping catalog-derived policy",
                    explicit_policy_raw,
                )

        return ProfileSummary(
            agent_preset=profile.agent_preset,
            task_role=profile.task_role,
            mood=profile.mood,
            execution_policy=profile.execution_policy,
            workflow_phase=profile.workflow_phase,
        )

    @classmethod
    def _hydrate_thread(cls, thread: GimoThread, raw_data: dict[str, Any]) -> GimoThread:
        metadata = thread.metadata if isinstance(thread.metadata, dict) else {}
        raw_agent_preset = str(raw_data.get("agent_preset") or "").strip() or None
        raw_mood = str(raw_data.get("mood") or thread.mood or "").strip() or None
        thread._legacy_missing_agent_preset = raw_agent_preset is None
        thread.proposed_plan = cls._canonicalize_proposed_plan(thread.proposed_plan)
        thread.workflow_phase = cls._derive_workflow_phase(
            raw_data.get("workflow_phase") or thread.workflow_phase,
            proposed_plan=thread.proposed_plan,
            metadata=metadata,
        )

        summary = cls._derive_profile_summary(
            agent_preset=raw_agent_preset,
            legacy_mood=raw_mood,
            workflow_phase=thread.workflow_phase,
            metadata=metadata,
        )
        thread.profile_summary = summary
        thread.agent_preset = str(summary.agent_preset or thread.agent_preset or "plan_orchestrator")
        return thread

    @classmethod
    def _schedule_notification(cls, coro: Any) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                coro.close()
            except Exception:
                pass
            return
        task = asyncio.create_task(coro)
        cls._notification_tasks.add(task)
        task.add_done_callback(cls._notification_tasks.discard)

    @classmethod
    def _load_thread_unlocked(cls, thread_id: str) -> Optional[GimoThread]:
        path = cls._thread_path(thread_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            thread = GimoThread.model_validate(data)
            return cls._hydrate_thread(thread, data)
        except Exception as e:
            logger.error("Error loading thread %s: %s", sanitize_for_log(thread_id), e)
            return None

    @classmethod
    def _write_thread_unlocked(cls, thread: GimoThread) -> None:
        cls._ensure_dir()
        thread = cls._hydrate_thread(thread, thread.model_dump(mode="json"))
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
                thread = cls._hydrate_thread(GimoThread.model_validate(data), data)
                if workspace_root and thread.workspace_root != workspace_root:
                    continue
                threads.append(thread)
            except Exception as e:
                logger.error("Error loading thread %s: %s", sanitize_for_log(p.name), e)
        
        # Sort by updated_at descending
        return sorted(threads, key=lambda t: t.updated_at, reverse=True)

    @classmethod
    def get_thread(cls, thread_id: str) -> Optional[GimoThread]:
        return cls._load_thread_unlocked(thread_id)

    @classmethod
    def create_thread(
        cls, workspace_root: str, title: str = "New Conversation", surface: str = "operator",
    ) -> GimoThread:
        cls._ensure_dir()
        thread = GimoThread(
            workspace_root=workspace_root,
            title=title,
            metadata=WorkspacePolicyService.default_metadata_for_surface(surface),
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
        normalized = str(agent_id or "").strip().lower()
        if not normalized:
            raise ValueError("agent_id is required")
        if not cls._AGENT_ID_RE.match(normalized):
            raise ValueError(
                f"Invalid agent_id '{normalized}'. Must match [a-zA-Z][a-zA-Z0-9_-]{{0,63}}"
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
        fork_metadata = dict(source.metadata or {})
        fork_metadata.update({"forked_from": thread_id, "forked_at_turn": turn_id})
             
        new_thread = GimoThread(
            workspace_root=source.workspace_root,
            title=new_title or f"Fork of {source.title}",
            turns=new_turns,
            metadata=fork_metadata,
            mood=source.mood,
            agent_preset=source.agent_preset,
            workflow_phase=source.workflow_phase,
            profile_summary=source.profile_summary.model_copy(deep=True) if source.profile_summary else None,
            proposed_plan=json.loads(json.dumps(source.proposed_plan)) if source.proposed_plan is not None else None,
        )
        cls.save_thread(new_thread)
        return new_thread

    @staticmethod
    def _extract_turns_up_to(thread: GimoThread, turn_id: str) -> List[GimoTurn]:
        """Helper to extract a slice of turns for forking."""
        subset = []
        for turn in thread.turns:
            subset.append(turn.model_copy(deep=True))
            if turn.id == turn_id:
                return subset
        return []
