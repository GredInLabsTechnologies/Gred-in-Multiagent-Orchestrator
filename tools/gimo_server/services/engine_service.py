from __future__ import annotations
import logging
from importlib import import_module
from typing import Any, Dict, List, Optional
from ..engine.pipeline import Pipeline

logger = logging.getLogger("orchestrator.services.engine")

# Keys that child_context is not permitted to override.
# These govern composition selection and orchestration invariants.
_PROTECTED_CONTEXT_KEYS: frozenset[str] = frozenset({
    "intent_effective",
    "intent_class",
    "spawn_depth",
    "multi_agent",
    "wake_on_demand",
    "child_run_mode",
    "custom_plan_id",
    "structured",
    "execution_decision",
    "workspace_root",
})

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
            "tools.gimo_server.engine.stages.llm_execute:LlmExecute",
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
            "tools.gimo_server.engine.stages.spawn_agents:SpawnAgentsStage",
            "tools.gimo_server.engine.stages.subagent_gate:SubagentGate",
        ],
        # Child agent task: ACE self-assesses, then execute + review
        "agent_task": [
            "tools.gimo_server.engine.stages.policy_gate:PolicyGate",
            "tools.gimo_server.engine.stages.risk_gate:RiskGate",
            "tools.gimo_server.engine.stages.cognitive_assessment:CognitiveAssessmentStage",
            "tools.gimo_server.engine.stages.llm_execute:LlmExecute",
            "tools.gimo_server.engine.stages.subdivide_router:SubdivideRouter",
            "tools.gimo_server.engine.stages.file_write:FileWrite",
            "tools.gimo_server.engine.stages.review_gate:ReviewGate",
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

        # Ensure the run is in 'running' state before executing.
        # When the worker picks up a 'pending' run directly (e.g. child runs
        # or re-queued runs from SubdivideRouter), the HTTP router has NOT
        # set the status yet — so we do it here to satisfy ChildRunService's
        # spawnable-state check and to have accurate status tracking.
        if run.status == "pending":
            OpsService.update_run_status(
                run_id, "running", msg="Execution started via RunWorker"
            )

        approved = OpsService.get_approved(run.approved_id)
        draft = OpsService.get_draft(approved.draft_id) if approved else None
        context = dict((draft.context if draft else {}) or {})

        # Inject draft prompt into context so LLM stages have access to it
        if draft and getattr(draft, "prompt", None) and "prompt" not in context:
            context["prompt"] = draft.prompt

        # Child-specific context overrides parent draft context.
        # Protected keys (orchestration invariants) cannot be overridden by a child.
        if getattr(run, "child_context", None):
            safe_overrides = {
                k: v for k, v in run.child_context.items()
                if k not in _PROTECTED_CONTEXT_KEYS
            }
            context.update(safe_overrides)
        if getattr(run, "child_prompt", None):
            context["prompt"] = run.child_prompt

        # For child runs, strip parent-orchestration keys inherited from the
        # draft context.  A child should never see wake_on_demand or the
        # parent's child_tasks list — only its OWN child_context determines
        # whether it spawns further sub-agents (fractal).
        if getattr(run, "parent_run_id", None):
            own_child_tasks = (run.child_context or {}).get("child_tasks")
            context.pop("wake_on_demand", None)
            context.pop("multi_agent", None)
            if not own_child_tasks:
                context.pop("child_tasks", None)

        # Log explicit GICS degradation so operators know when historical reliability
        # is unavailable and routing falls back to static priors.
        try:
            gics = getattr(OpsService, "_gics", None)
            gics_available = bool(gics and getattr(gics, "_client", None))
        except Exception:
            gics_available = False
        if not gics_available:
            logger.warning(
                "[GICS_DEGRADED] run=%s — GICS unavailable, routing decisions fall back to static priors. "
                "Historical reliability data not consulted.",
                run_id,
            )
            OpsService.append_log(
                run_id, level="WARN",
                msg="[GICS_DEGRADED] Historical reliability unavailable — routing uses static priors."
            )

        # Valid explicit execution modes — checked before heuristic inference.
        _VALID_EXECUTION_MODES = {
            "legacy_run", "file_task", "structured_plan",
            "multi_agent", "agent_task", "merge_gate", "custom_plan",
        }

        # Infer composition if not provided
        if not composition:
            # Honour an explicit execution_mode from context first (avoids heuristic drift).
            explicit_mode = context.get("execution_mode")
            if explicit_mode and explicit_mode in _VALID_EXECUTION_MODES:
                composition = explicit_mode
            elif context.get("custom_plan_id"):
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
            elif getattr(run, "parent_run_id", None):
                if context.get("child_tasks"):
                    # Fractal: this child decided to decompose further into sub-agents
                    composition = "multi_agent"
                else:
                    # Standard child: execute task + request orchestrator review
                    composition = "agent_task"
            elif context.get("structured"):
                composition = "structured_plan"
            elif context.get("intent_effective") in {"MERGE_REQUEST", "CORE_RUNTIME_CHANGE", "SECURITY_CHANGE"}:
                composition = "merge_gate"
            elif context.get("target_path") or context.get("target_file"):
                composition = "file_task"
            else:
                composition = "legacy_run"

        # For file_task, override prompt to ask for raw file content only
        if composition == "file_task" and context.get("prompt"):
            target = context.get("target_path") or context.get("target_file", "file.md")
            import os as _os
            filename = _os.path.basename(str(target))
            context["prompt"] = (
                f"Generate ONLY the raw file content for '{filename}'. "
                f"Do not include any explanation, preamble, or markdown code fences — "
                f"output exactly what should be written to the file.\n\n"
                f"Task: {context['prompt']}"
            )

        # Start pipeline
        try:
            results = await cls.run_composition(composition, run_id, context)
        except Exception as exc:
            OpsService.update_run_status(run_id, "error", msg=f"Pipeline error: {str(exc)[:200]}")
            raise

        # Update run status based on pipeline outcome
        final_status = "done"
        final_msg = "Pipeline completed successfully"
        for stage_output in results:
            if stage_output.status == "fail":
                final_status = "error"
                final_msg = stage_output.artifacts.get("error", "Stage failed")
                break
            if stage_output.status == "halt":
                # Already halted (e.g. HUMAN_APPROVAL_REQUIRED) — leave status as-is
                return results

        OpsService.update_run_status(run_id, final_status, msg=final_msg)
        return results
