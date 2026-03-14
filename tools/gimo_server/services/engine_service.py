from __future__ import annotations
from importlib import import_module
from typing import Any, Dict, List, Optional
from ..engine.pipeline import Pipeline

class EngineService:
    """Entry point for executing unified pipelines."""

    _COMPOSITION_MAP: Dict[str, List[str]] = {
        "merge_gate": [
            "tools.gimo_server.engine.stages.policy_gate:PolicyGate",
            "tools.gimo_server.engine.stages.risk_gate:RiskGate",
            "tools.gimo_server.engine.stages.git_pipeline:GitPipeline",
        ],
        "structured_plan": [
            "tools.gimo_server.engine.stages.policy_gate:PolicyGate",
            "tools.gimo_server.engine.stages.risk_gate:RiskGate",
            "tools.gimo_server.engine.stages.plan_stage:PlanStage",
            "tools.gimo_server.engine.stages.llm_execute:LlmExecute",
        ],
        "file_task": [
            "tools.gimo_server.engine.stages.policy_gate:PolicyGate",
            "tools.gimo_server.engine.stages.risk_gate:RiskGate",
            "tools.gimo_server.engine.stages.file_write:FileWrite",
        ],
        "legacy_run": [
            "tools.gimo_server.engine.stages.policy_gate:PolicyGate",
            "tools.gimo_server.engine.stages.risk_gate:RiskGate",
            "tools.gimo_server.engine.stages.llm_execute:LlmExecute",
            "tools.gimo_server.engine.stages.critic:Critic",
        ],
        "custom_plan": [
            "tools.gimo_server.engine.stages.policy_gate:PolicyGate",
            "tools.gimo_server.engine.stages.risk_gate:RiskGate",
            "tools.gimo_server.engine.stages.plan_stage:PlanStage",
        ],
        "slice0": [
            "tools.gimo_server.engine.stages.policy_gate:PolicyGate",
            "tools.gimo_server.engine.stages.risk_gate:RiskGate",
            "tools.gimo_server.engine.stages.plan_stage:PlanStage",
            "tools.gimo_server.engine.stages.llm_execute:LlmExecute",
            "tools.gimo_server.engine.stages.qa_gate:QaGate",
        ],
        "multi_agent": [
            "tools.gimo_server.engine.stages.policy_gate:PolicyGate",
            "tools.gimo_server.engine.stages.risk_gate:RiskGate",
            "tools.gimo_server.engine.stages.plan_stage:PlanStage",
            "tools.gimo_server.engine.stages.llm_execute:LlmExecute",
            "tools.gimo_server.engine.stages.subagent_gate:SubagentGate",
        ],
    }

    @staticmethod
    def _resolve_stage(stage_ref: str) -> Any:
        module_name, class_name = stage_ref.split(":", 1)
        module = import_module(module_name)
        return getattr(module, class_name)

    @classmethod
    def _build_stages(cls, composition_name: str) -> List[Any]:
        stage_refs = cls._COMPOSITION_MAP.get(composition_name)
        if not stage_refs:
            raise ValueError(f"Unknown composition: {composition_name}")
        stage_types = [cls._resolve_stage(ref) for ref in stage_refs]
        return [stage_type() for stage_type in stage_types]

    @staticmethod
    async def run_composition(
        composition_name: str, 
        run_id: str, 
        initial_context: Dict[str, Any]
    ) -> List[Any]:
        stages = EngineService._build_stages(composition_name)
        pipeline = Pipeline(run_id=run_id, stages=stages)
        return await pipeline.run(initial_context)

    @classmethod
    async def execute_run(cls, run_id: str, composition: Optional[str] = None):
        """Unified execution for any run."""
        from .ops_service import OpsService

        run = OpsService.get_run(run_id)
        if not run:
            return []

        approved = OpsService.get_approved(run.approved_id)
        draft = OpsService.get_draft(approved.draft_id) if approved else None
        context = dict((draft.context if draft else {}) or {})

        # Infer composition if not provided
        if not composition:
            if context.get("custom_plan_id"):
                composition = "custom_plan"
            elif (
                bool(context.get("multi_agent"))
                or bool(context.get("wake_on_demand"))
                or str(context.get("child_run_mode") or "").lower() == "parent"
                or bool(getattr(run, "child_run_ids", []))
                or int(getattr(run, "awaiting_count", 0) or 0) > 0
            ):
                # Explicit parent/child orchestration mode for wake-on-demand flows.
                composition = "multi_agent"
            elif context.get("structured"):
                composition = "structured_plan"
            elif context.get("intent_effective") in {"MERGE_REQUEST", "CORE_RUNTIME_CHANGE", "SECURITY_CHANGE"}:
                composition = "merge_gate"
            elif context.get("target_path") or context.get("target_file"):
                composition = "file_task"
            else:
                composition = "legacy_run"

        # Start pipeline
        return await cls.run_composition(composition, run_id, context)
