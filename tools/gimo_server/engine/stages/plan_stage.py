from __future__ import annotations
from ..contracts import StageInput, StageOutput, ExecutionStage
from ...services.custom_plan_service import CustomPlanService

class PlanStage(ExecutionStage):
    @property
    def name(self) -> str:
        return "plan_stage"

    async def execute(self, input: StageInput) -> StageOutput:
        plan_id = input.context.get("plan_id") or input.context.get("custom_plan_id")
        plan_data = input.context.get("plan_data")
        
        if not plan_id and not plan_data:
            return StageOutput(status="fail", artifacts={"error": "Missing plan_id or plan_data"}, error="Missing plan_id or plan_data")
            
        # If plan_data is provided, create a plan first.
        if plan_data and not plan_id:
            try:
                generated = CustomPlanService.create_plan_from_llm(
                    plan_data,
                    name=str(input.context.get("plan_name") or "Generated Plan"),
                    description=str(input.context.get("plan_description") or ""),
                )
                plan_id = generated.id
            except Exception as e:
                return StageOutput(status="fail", artifacts={"error": f"Invalid plan_data: {str(e)}"}, error=f"Invalid plan_data: {str(e)}")

        # Load from store
        if plan_id:
            plan = CustomPlanService.get_plan(plan_id)
        else:
            return StageOutput(status="fail", artifacts={"error": "Unable to resolve plan_id"}, error="Unable to resolve plan_id")
            
        if not plan:
            return StageOutput(status="fail", artifacts={"error": f"Plan {plan_id} not found"}, error=f"Plan {plan_id} not found")
            
        try:
            executed_plan = await CustomPlanService.execute_plan(plan_id)
            if executed_plan.status == "done":
                return StageOutput(
                    status="continue",
                    artifacts={"executed_plan": executed_plan.model_dump(), "plan_id": plan_id},
                )
            # Aggregate node-level errors into a causal error summary
            failed_nodes = [n for n in executed_plan.nodes if n.status == "error"]
            error_detail = "; ".join(
                f"{n.id}: {(n.error or 'no detail')[:200]}" for n in failed_nodes
            ) or "plan execution failed (no node detail)"
            return StageOutput(
                status="fail",
                artifacts={
                    "executed_plan": executed_plan.model_dump(),
                    "plan_id": plan_id,
                    "error": error_detail,
                    "stage": "plan_execution",
                },
                error=error_detail,
                caused_by="plan_execution",
            )
        except Exception as e:
            return StageOutput(
                status="fail",
                artifacts={"error": str(e)},
                error=str(e),
                caused_by="plan_stage_exception",
            )

    async def rollback(self, input: StageInput) -> None:
        pass # CustomPlanService doesn't have a clear rollback yet
