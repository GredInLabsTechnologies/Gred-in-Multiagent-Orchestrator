from __future__ import annotations
from ..contracts import StageInput, StageOutput, ExecutionStage
from ...services.merge_gate_service import MergeGateService

class GitPipeline(ExecutionStage):
    name = "git_pipeline"

    async def execute(self, input: StageInput) -> StageOutput:
        run_id = input.run_id
        
        try:
            handled = await MergeGateService.execute_run(run_id)
            
            if handled:
                return StageOutput(status="continue", artifacts={"git_pipeline_result": {"handled": True}})
            return StageOutput(
                status="fail",
                artifacts={"git_pipeline_result": {"handled": False}},
                error="git pipeline did not handle the run",
            )
        except Exception as e:
            return StageOutput(status="fail", artifacts={"error": str(e)}, error=str(e))

    async def rollback(self, input: StageInput) -> None:
        # Revert merge/branch if needed
        pass
