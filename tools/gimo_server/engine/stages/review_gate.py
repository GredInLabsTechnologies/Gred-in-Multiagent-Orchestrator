"""Pipeline stage that requests orchestrator review (GO/NO-GO) of agent output.

Creates an ActionDraft with the run output and pauses the child run in
``awaiting_review`` status. The orchestrator (Claude via MCP) then calls
POST /action-drafts/{id}/approve (GO) or POST /action-drafts/{id}/reject
(NO-GO with reason). On rejection, the run is re-queued with the feedback
appended to its child_context.
"""
from __future__ import annotations

import logging

from ..contracts import StageInput, StageOutput

logger = logging.getLogger(__name__)

# Timeout (seconds) waiting for orchestrator review
REVIEW_TIMEOUT = 600.0


class ReviewGate:
    name = "review_gate"

    async def execute(self, input: StageInput) -> StageOutput:
        from ...services.ops import OpsService
        from ...services.hitl_gate_service import HitlGateService

        run = OpsService.get_run(input.run_id)
        if not run:
            return StageOutput(status="fail", error="Run not found")

        # Skip review gate for parent orchestrator runs (no parent_run_id)
        if not run.parent_run_id:
            return StageOutput(status="continue")

        child_ctx = run.child_context or {}

        # Collect output from previous stages
        llm_content = str(input.artifacts.get("content") or "")
        file_results = input.artifacts.get("file_op_results", [])
        task_id = child_ctx.get("task_id", run.id)
        role = child_ctx.get("role", "agent")

        summary = llm_content[:2000] if llm_content else str(file_results)[:2000]

        OpsService.append_log(
            input.run_id, level="INFO",
            msg=f"ReviewGate: requesting orchestrator review for task '{task_id}' (role: {role})"
        )

        # Pause run in awaiting_review
        OpsService.update_run_status(
            input.run_id, "awaiting_review",
            msg=f"Awaiting orchestrator review for task '{task_id}'"
        )

        # Create review action draft via HitlGateService
        decision = await HitlGateService.gate_tool_call(
            agent_id=input.run_id,
            tool="review_agent_output",
            params={
                "run_id": input.run_id,
                "task_id": task_id,
                "role": role,
                "output_summary": summary,
                "parent_run_id": run.parent_run_id,
            },
            timeout_seconds=REVIEW_TIMEOUT,
        )

        if decision == "allow":
            # GO — mark approved and continue
            OpsService.update_run_status(
                input.run_id, "running",
                msg=f"ReviewGate: GO received for task '{task_id}'. Continuing."
            )
            # Learning loop: record success in CapabilityProfile
            _record_capability(run, child_ctx, success=True)
            return StageOutput(status="continue", artifacts={"review_decision": "approved"})

        # NO-GO — load rejection reason and re-queue with feedback
        reason = _get_reject_reason(input.run_id)
        OpsService.append_log(
            input.run_id, level="WARN",
            msg=f"ReviewGate: NO-GO for task '{task_id}'. Reason: {reason}. Re-queuing with feedback."
        )
        # Learning loop: record failure in CapabilityProfile
        _record_capability(run, child_ctx, success=False, failure_reason=reason)

        # Re-queue: update child_context with feedback and reset to pending
        with OpsService._lock():
            fresh = OpsService._load_run_metadata(input.run_id)
            if fresh:
                ctx = dict(fresh.child_context or {})
                ctx["feedback"] = reason
                ctx.pop("_review_approved", None)
                fresh.child_context = ctx
                fresh.status = "pending"
                fresh.attempt = fresh.attempt + 1
                OpsService._persist_run(fresh)

        # Notify worker
        try:
            from ...services.authority import ExecutionAuthority
            ExecutionAuthority.get().run_worker.notify()
        except Exception:
            pass

        # Return halt so pipeline doesn't mark run as done
        return StageOutput(
            status="halt",
            artifacts={"review_decision": "rejected", "feedback": reason},
        )

    async def rollback(self, input: StageInput) -> None:
        pass


def _record_capability(run, child_ctx: dict, *, success: bool, failure_reason: str = "") -> None:
    """Record GO/NO-GO outcome in CapabilityProfile for the learning loop."""
    try:
        from ...services.capability_profile_service import CapabilityProfileService
        task_type = child_ctx.get("role") or child_ctx.get("task_type") or "general"
        model_id = child_ctx.get("model") or ""
        provider_type = (run.child_context or {}).get("provider_type") or "unknown"
        CapabilityProfileService.record_task_outcome(
            provider_type=provider_type,
            model_id=model_id,
            task_type=task_type,
            success=success,
            failure_reason=failure_reason,
        )
    except Exception:
        pass


def _get_reject_reason(run_id: str) -> str:
    """Retrieve the most recent rejection reason from the action draft store."""
    try:
        from ...services.hitl_gate_service import HitlGateService
        drafts = HitlGateService.list_drafts(status="rejected")
        for d in drafts:
            if d.params.get("run_id") == run_id:
                return d.decision_reason or "No reason provided"
    except Exception:
        pass
    return "No reason provided"
