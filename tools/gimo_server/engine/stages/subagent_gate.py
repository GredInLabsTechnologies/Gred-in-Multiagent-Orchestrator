"""Pipeline stage that pauses a run when it has pending child runs."""
from __future__ import annotations
import logging
from ..contracts import StageInput, StageOutput

logger = logging.getLogger(__name__)


class SubagentGate:
    """Checks if run has pending children and halts (pauses) if so."""
    name = "subagent_gate"

    async def execute(self, input: StageInput) -> StageOutput:
        from ...services.ops_service import OpsService
        run = OpsService.get_run(input.run_id)
        if not run:
            return StageOutput(status="fail", error="Run not found")
        if run.awaiting_count > 0:
            OpsService.update_run_status(
                input.run_id, "awaiting_subagents",
                msg=f"Halting pipeline: {run.awaiting_count} child run(s) pending"
            )
            return StageOutput(
                status="halt",
                artifacts={"reason": "awaiting_subagents", "children": run.child_run_ids},
            )
        return StageOutput(status="continue")

    async def rollback(self, input: StageInput) -> None:
        pass
