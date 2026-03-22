from __future__ import annotations
from ..contracts import StageInput, StageOutput, ExecutionStage
from ...services.merge_gate_service import MergeGateService

class GitPipeline(ExecutionStage):
    name = "git_pipeline"

    async def execute(self, input: StageInput) -> StageOutput:
        run_id = input.run_id
        
        try:
            handled = await MergeGateService.execute_run(run_id)
            
            return StageOutput(
                status="continue" if handled else "fail",
                artifacts={"git_pipeline_result": {"handled": bool(handled)}}
            )
        except Exception as e:
            return StageOutput(status="fail", artifacts={"error": str(e)})

    async def rollback(self, input: StageInput) -> None:
        # Revert merge/branch if needed
        pass
