"""Pipeline stage that spawns child runs from the context's child_tasks list.

Implements dynamic wave-based spawning with fractal safety guardrails:
- Wave N: spawn all tasks whose dependencies (by task id) are already done.
- Halts after each wave (awaiting_subagents) until children complete.
- When all tasks are done and awaiting_count == 0, continues to next stage.
- Enforces max_spawn_depth (default 2) to prevent exponential explosion.
- Enforces model tier constraint: children cannot use a higher tier than parent.
- On violation, emits a ComplexityEscalation action draft to the orchestrator.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional, Set

from ..contracts import StageInput, StageOutput

logger = logging.getLogger(__name__)

# Default max fractal depth (0 = root, 1 = first-gen children, 2 = grandchildren)
DEFAULT_MAX_SPAWN_DEPTH = 2

# Strong refs for fire-and-forget escalation tasks so they are not GC'd mid-flight.
_BG_ESCALATION_TASKS: Set[asyncio.Task] = set()


def _resolve_task_tier(task: Dict[str, Any]) -> Optional[int]:
    """Get the quality_tier for a task's requested model, if any."""
    model_id = (task.get("context") or {}).get("model") or task.get("model")
    if not model_id:
        return None
    try:
        from ...services.model_inventory_service import ModelInventoryService
        entry = ModelInventoryService.find_model(model_id)
        return entry.quality_tier if entry else None
    except Exception:
        return None


class SpawnAgentsStage:
    name = "spawn_agents"

    async def execute(self, input: StageInput) -> StageOutput:
        from ...services.ops import OpsService
        from ...services.child_run_service import ChildRunService

        run = OpsService.get_run(input.run_id)
        if not run:
            return StageOutput(status="fail", error="Run not found")

        child_tasks: List[Dict[str, Any]] = input.context.get("child_tasks", [])
        if not child_tasks:
            # No multi-agent plan — proceed as normal
            return StageOutput(status="continue")

        # Build set of task_ids already spawned (by inspecting child runs)
        spawned_task_ids: Set[str] = set()
        done_task_ids: Set[str] = set()

        for child_run_id in run.child_run_ids:
            child = OpsService.get_run(child_run_id)
            if not child:
                continue
            child_ctx = child.child_context or {}
            tid = child_ctx.get("task_id")
            if tid:
                spawned_task_ids.add(tid)
                if child.status == "done":
                    done_task_ids.add(tid)

        all_task_ids = {t.get("id") for t in child_tasks if t.get("id")}

        # All tasks spawned and done → continue to next stage
        if all_task_ids and all_task_ids <= done_task_ids and run.awaiting_count == 0:
            OpsService.append_log(
                input.run_id, level="INFO",
                msg="SpawnAgentsStage: all tasks completed. Continuing pipeline."
            )
            return StageOutput(status="continue", artifacts={"all_tasks_done": True})

        # Still waiting for in-progress children
        if run.awaiting_count > 0:
            OpsService.update_run_status(
                input.run_id, "awaiting_subagents",
                msg=f"Waiting for {run.awaiting_count} child run(s) to complete."
            )
            return StageOutput(
                status="halt",
                artifacts={"reason": "awaiting_subagents", "pending": run.awaiting_count},
            )

        # --- Fractal guardrails ---
        max_depth = int(input.context.get("max_spawn_depth", DEFAULT_MAX_SPAWN_DEPTH))
        parent_tier = run.model_tier  # None means unrestricted (root orchestrator)

        if run.spawn_depth >= max_depth:
            # Depth limit hit — escalate to orchestrator instead of spawning
            reason = (
                f"Depth limit reached (spawn_depth={run.spawn_depth}, max={max_depth}). "
                "Cannot spawn further children. Task needs orchestrator intervention."
            )
            OpsService.append_log(input.run_id, level="WARN", msg=f"SpawnAgentsStage: {reason}")
            await _emit_escalation(input.run_id, reason, input.context)
            OpsService.update_run_status(
                input.run_id, "awaiting_review",
                msg="Complexity escalation: depth limit. Awaiting orchestrator decision."
            )
            return StageOutput(status="halt", artifacts={"reason": "depth_limit_escalation"})

        # Find tasks ready to spawn this wave
        ready_tasks = [
            t for t in child_tasks
            if t.get("id") not in spawned_task_ids
            and all(dep in done_task_ids for dep in t.get("depends_on", []))
        ]

        if not ready_tasks:
            OpsService.append_log(
                input.run_id, level="WARN",
                msg="SpawnAgentsStage: no ready tasks but awaiting_count == 0. Continuing."
            )
            return StageOutput(status="continue")

        # Validate tier constraint: children cannot use a higher tier than parent
        if parent_tier is not None:
            tier_violations = [
                t for t in ready_tasks
                if (_resolve_task_tier(t) or 0) > parent_tier
            ]
            if tier_violations:
                ids = [t.get("id", "?") for t in tier_violations]
                reason = (
                    f"Tier violation: tasks {ids} request model tier above parent tier {parent_tier}. "
                    "A lower-tier worker cannot spawn higher-tier workers."
                )
                OpsService.append_log(input.run_id, level="WARN", msg=f"SpawnAgentsStage: {reason}")
                await _emit_escalation(input.run_id, reason, input.context)
                OpsService.update_run_status(
                    input.run_id, "awaiting_review",
                    msg="Complexity escalation: tier constraint. Awaiting orchestrator decision."
                )
                return StageOutput(status="halt", artifacts={"reason": "tier_constraint_escalation"})

        # Spawn this wave
        spawned = []
        for task in ready_tasks:
            task_id = task.get("id") or f"task_{uuid.uuid4().hex[:8]}"
            child_ctx = dict(task.get("context", {}))
            child_ctx["task_id"] = task_id
            child_ctx["role"] = task.get("role", "")

            child = ChildRunService.spawn_child(
                parent_run_id=input.run_id,
                prompt=task.get("prompt", ""),
                context=child_ctx,
                agent_profile_role=task.get("role"),
            )
            spawned.append(child.id)
            OpsService.append_log(
                input.run_id, level="INFO",
                msg=f"SpawnAgentsStage: spawned child {child.id} for task '{task_id}' (depth {run.spawn_depth + 1})"
            )

        # Notify worker so it picks up new pending children promptly
        try:
            from ...services.authority import ExecutionAuthority
            ExecutionAuthority.get().run_worker.notify()
        except Exception:
            pass  # Worker will pick up on next poll

        # Pause parent
        ChildRunService.pause_parent(input.run_id)
        return StageOutput(
            status="halt",
            artifacts={"reason": "awaiting_subagents", "spawned": spawned},
        )

    async def rollback(self, input: StageInput) -> None:
        pass


async def _emit_escalation(run_id: str, reason: str, context: Dict[str, Any]) -> None:
    """Create a complexity escalation ActionDraft so the orchestrator can decide
    whether to subdivide, multi-pass, or reassign to a higher-tier worker.
    Also records the failure in GICS so it can learn to avoid this pattern.
    """
    from ...services.hitl_gate_service import HitlGateService
    from ...services.ops import OpsService

    run = OpsService.get_run(run_id)
    task_type = (context.get("task_type") or context.get("role") or "general")
    model_id = context.get("model") or ""
    provider_type = context.get("provider_type") or "unknown"

    # Record failure in GICS so it learns this model/task_type combination is problematic
    try:
        from ...services.ops import OpsService
        OpsService.record_model_outcome(
            provider_type=provider_type,
            model_id=model_id,
            success=False,
            task_type=task_type,
        )
        logger.info("GICS: recorded complexity failure for model=%s task_type=%s", model_id, task_type)
    except Exception as exc:
        logger.warning("GICS record failed (non-critical): %s", exc)

    # Emit escalation action draft via HitlGateService (non-blocking fire-and-forget)
    async def _gate():
        try:
            await HitlGateService.gate_tool_call(
                agent_id=run_id,
                tool="complexity_escalation",
                params={
                    "run_id": run_id,
                    "reason": reason,
                    "task_type": task_type,
                    "model_id": model_id,
                    "spawn_depth": run.spawn_depth if run else 0,
                    "options": ["subdivide", "multi_pass", "reassign_higher_tier"],
                },
                timeout_seconds=600.0,
            )
        except Exception as exc:
            logger.warning("Escalation gate error (non-critical): %s", exc)

    _task = asyncio.create_task(_gate())
    _BG_ESCALATION_TASKS.add(_task)
    _task.add_done_callback(_BG_ESCALATION_TASKS.discard)
