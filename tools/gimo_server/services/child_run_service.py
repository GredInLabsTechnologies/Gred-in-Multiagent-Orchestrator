"""Service for spawning child OpsRuns from a parent run."""
from __future__ import annotations
import uuid
import logging
from typing import Any, Dict, List, Optional

from ..ops_models import OpsRun
from .ops import OpsService

logger = logging.getLogger("orchestrator.services.child_run")


class ChildRunService:
    """Manages parent-child OpsRun lifecycle."""

    @staticmethod
    def spawn_child(
        parent_run_id: str,
        prompt: str,
        context: Dict[str, Any] = None,
        agent_profile_role: Optional[str] = None,
    ) -> OpsRun:
        parent = OpsService.get_run(parent_run_id)
        if not parent:
            raise ValueError(f"Parent run {parent_run_id} not found")
        if parent.status not in ("running", "awaiting_subagents"):
            raise ValueError(f"Parent run {parent_run_id} not in spawnable state: {parent.status}")

        child_id = f"r_{uuid.uuid4().hex[:12]}"
        child_ctx = dict(context or {})
        # Inherit or resolve model tier for the child
        child_tier = child_ctx.get("model_tier") or parent.model_tier
        if child_tier is None:
            try:
                from .model_inventory_service import ModelInventoryService
                model_id = child_ctx.get("model") or ""
                entry = ModelInventoryService.find_model(model_id) if model_id else None
                child_tier = entry.quality_tier if entry else None
            except Exception:
                child_tier = None

        child = OpsRun(
            id=child_id,
            approved_id=parent.approved_id,
            status="pending",
            parent_run_id=parent_run_id,
            repo_id=parent.repo_id,
            draft_id=parent.draft_id,
            child_prompt=prompt,
            child_context=child_ctx,
            spawn_depth=parent.spawn_depth + 1,
            model_tier=child_tier,
        )

        # OpsService is file-backed — use its internal persistence API under the file lock
        with OpsService._lock():
            OpsService.RUNS_DIR.mkdir(parents=True, exist_ok=True)
            OpsService._persist_run(child)
            OpsService._append_run_log_entry(child_id, level="INFO", msg=f"Child run created from parent {parent_run_id}")

            # Reload parent fresh from disk (inside lock) then update and persist
            fresh_parent = OpsService._load_run_metadata(parent_run_id)
            if not fresh_parent:
                raise ValueError(f"Parent run {parent_run_id} disappeared during spawn")
            fresh_parent.child_run_ids.append(child_id)
            fresh_parent.awaiting_count += 1
            OpsService._persist_run(fresh_parent)

        OpsService.append_log(
            parent_run_id, level="INFO",
            msg=f"Spawned child run {child_id} (total children: {len(fresh_parent.child_run_ids)})"
        )
        return child

    @staticmethod
    def pause_parent(parent_run_id: str) -> None:
        parent = OpsService.get_run(parent_run_id)
        if not parent:
            raise ValueError(f"Parent run {parent_run_id} not found")
        if parent.awaiting_count == 0:
            raise ValueError("Cannot pause: no children pending")
        OpsService.update_run_status(
            parent_run_id, "awaiting_subagents",
            msg=f"Paused. Waiting for {parent.awaiting_count} child run(s)."
        )

    @staticmethod
    def get_children_status(parent_run_id: str) -> List[Dict[str, Any]]:
        parent = OpsService.get_run(parent_run_id)
        if not parent:
            return []
        result = []
        for cid in parent.child_run_ids:
            child = OpsService.get_run(cid)
            if child:
                result.append({
                    "id": child.id,
                    "status": child.status,
                    "started_at": child.started_at.isoformat() if child.started_at else None,
                })
        return result
