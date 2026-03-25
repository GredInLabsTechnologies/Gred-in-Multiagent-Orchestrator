from __future__ import annotations
import logging
from enum import Enum, auto
from importlib import import_module
from typing import Any, Dict, List, Optional, Tuple
from ..engine.pipeline import Pipeline

logger = logging.getLogger("orchestrator.services.engine")


class ContextPolicy(Enum):
    """Policy governing whether a context field can be overridden by a child run.

    IMMUTABLE       — Set by the orchestrator at run creation. A child cannot
                      change this field. Attempts are blocked and logged.
                      This is the safe default for unknown fields (fail-closed).

    CHILD_OVERRIDABLE — The child run may set or override this field. Used for
                        task-specific parameters that legitimately vary per child
                        (prompt, target_path, model, etc.).

    CHILD_EXCLUSIVE  — This field is meaningful only when set by a child. It is
                       automatically stripped from the parent context before a
                       child run executes, ensuring fractal runs don't inherit
                       parent orchestration state.

    PARENT_ONLY     — Valid only in the parent orchestrator context. Automatically
                      stripped when executing as a child run, regardless of whether
                      the child sets it. A child that explicitly sets this field is
                      also blocked. Prevents parent orchestration flags from leaking
                      into child scopes or being injected upward.
    """
    IMMUTABLE = auto()
    CHILD_OVERRIDABLE = auto()
    CHILD_EXCLUSIVE = auto()
    PARENT_ONLY = auto()


# ── Context Field Registry ────────────────────────────────────────────────────
#
# Single source of truth for every context field's security policy.
# Adding a new field: pick its policy and add one line here. No other code
# needs to change. The merge function below reads this registry at call time.
#
# Default for unlisted fields: IMMUTABLE (fail-closed).
# If a new field should be child-overridable, add it here explicitly.
#
_CONTEXT_FIELD_REGISTRY: Dict[str, ContextPolicy] = {
    # ── Orchestration invariants (IMMUTABLE) ──────────────────────────────────
    # These determine composition, security posture and execution boundaries.
    # A child that overrides these could escape its execution scope.
    "intent_effective":   ContextPolicy.IMMUTABLE,
    "intent_class":       ContextPolicy.IMMUTABLE,
    "spawn_depth":        ContextPolicy.IMMUTABLE,
    "execution_decision": ContextPolicy.IMMUTABLE,
    "workspace_root":     ContextPolicy.IMMUTABLE,
    "execution_mode":     ContextPolicy.IMMUTABLE,

    # ── Parent-only orchestration flags (PARENT_ONLY) ─────────────────────────
    # These flags drive parent-level composition decisions (wake-on-demand,
    # multi-agent spawning). They are automatically stripped when the context
    # is applied to a child run — a child starts clean unless it sets them
    # explicitly in its own child_context, which is also blocked here.
    "multi_agent":        ContextPolicy.PARENT_ONLY,
    "wake_on_demand":     ContextPolicy.PARENT_ONLY,

    # ── Composition-determining flags (IMMUTABLE) ─────────────────────────────
    # These are read by the heuristic composition inference block.
    # A child cannot force a different composition on its parent's context.
    "child_run_mode":     ContextPolicy.IMMUTABLE,
    "custom_plan_id":     ContextPolicy.IMMUTABLE,
    "structured":         ContextPolicy.IMMUTABLE,

    # ── Child-overridable task parameters ─────────────────────────────────────
    # Legitimate per-child variation. A child sets its own task content,
    # routing preferences, and execution tuning within the bounds set here.
    "prompt":             ContextPolicy.CHILD_OVERRIDABLE,
    "task_id":            ContextPolicy.CHILD_OVERRIDABLE,
    "role":               ContextPolicy.CHILD_OVERRIDABLE,
    "target_path":        ContextPolicy.CHILD_OVERRIDABLE,
    "target_file":        ContextPolicy.CHILD_OVERRIDABLE,
    "file_path":          ContextPolicy.CHILD_OVERRIDABLE,
    "file_task_spec":     ContextPolicy.CHILD_OVERRIDABLE,
    "model":              ContextPolicy.CHILD_OVERRIDABLE,
    "provider_type":      ContextPolicy.CHILD_OVERRIDABLE,
    "task_type":          ContextPolicy.CHILD_OVERRIDABLE,
    "ace_multi_pass":     ContextPolicy.CHILD_OVERRIDABLE,
    "ace_max_passes":     ContextPolicy.CHILD_OVERRIDABLE,  # bounded in llm_execute.py
    "gen_context":        ContextPolicy.CHILD_OVERRIDABLE,
    "max_spawn_depth":    ContextPolicy.CHILD_OVERRIDABLE,
    "allowed_paths":      ContextPolicy.CHILD_OVERRIDABLE,

    # ── Child-exclusive fields ─────────────────────────────────────────────────
    # Valid only when set by the child itself. These are stripped from the
    # parent draft context before applying child overrides, so a child that
    # doesn't set them explicitly starts clean.
    "child_tasks":        ContextPolicy.CHILD_EXCLUSIVE,
}

_DEFAULT_CONTEXT_POLICY = ContextPolicy.IMMUTABLE  # fail-closed for unknown fields

# Valid explicit execution modes. Module-level so it is not recreated per call.
_VALID_EXECUTION_MODES: frozenset[str] = frozenset({
    "legacy_run", "file_task", "structured_plan",
    "multi_agent", "agent_task", "merge_gate", "custom_plan",
})


def _apply_child_context(
    base: Dict[str, Any],
    child_context: Dict[str, Any],
    *,
    is_child_run: bool = False,
) -> Tuple[Dict[str, Any], List[str]]:
    """Merge child_context into base according to the field registry.

    Returns (updated_base, blocked_keys).

    Rules:
    - IMMUTABLE keys in child_context are dropped and logged.
    - CHILD_OVERRIDABLE keys are applied.
    - CHILD_EXCLUSIVE keys in base are stripped first, then applied from child.
    - PARENT_ONLY keys are stripped from base when is_child_run=True, and are
      also blocked if the child tries to set them explicitly.
    - Unknown keys use _DEFAULT_CONTEXT_POLICY (IMMUTABLE → blocked).
    """
    blocked: List[str] = []

    # Strip CHILD_EXCLUSIVE keys that the parent draft may carry — a child that
    # doesn't explicitly set them should not inherit the parent's version.
    # Strip PARENT_ONLY keys when executing as a child run — these flags are
    # meaningful only in the parent orchestrator scope.
    for key, policy in _CONTEXT_FIELD_REGISTRY.items():
        if policy == ContextPolicy.CHILD_EXCLUSIVE:
            base.pop(key, None)
        elif policy == ContextPolicy.PARENT_ONLY and is_child_run:
            base.pop(key, None)

    for key, value in child_context.items():
        policy = _CONTEXT_FIELD_REGISTRY.get(key, _DEFAULT_CONTEXT_POLICY)
        if policy in (ContextPolicy.IMMUTABLE, ContextPolicy.PARENT_ONLY):
            blocked.append(key)
        else:
            base[key] = value

    if blocked:
        logger.warning(
            "[CHILD_CTX] Blocked %d immutable key override(s): %s",
            len(blocked),
            ", ".join(repr(k) for k in blocked),
        )

    return base, blocked

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

        # Child-specific context overrides — governed by _CONTEXT_FIELD_REGISTRY.
        # is_child_run=True causes PARENT_ONLY fields (wake_on_demand, multi_agent)
        # to be stripped from the inherited draft context, and blocks the child
        # from injecting them back. CHILD_EXCLUSIVE fields (child_tasks) are
        # stripped unless the child explicitly sets them in its own child_context.
        is_child_run = bool(getattr(run, "parent_run_id", None))
        if getattr(run, "child_context", None):
            context, _blocked = _apply_child_context(
                context, run.child_context, is_child_run=is_child_run
            )
            if _blocked:
                OpsService.append_log(
                    run_id, level="WARN",
                    msg=f"[CHILD_CTX] Blocked immutable key overrides: {_blocked}",
                )
        elif is_child_run:
            # No child_context provided but still a child run — strip PARENT_ONLY
            # and CHILD_EXCLUSIVE fields inherited from the parent draft context.
            context, _ = _apply_child_context(context, {}, is_child_run=True)
        if getattr(run, "child_prompt", None):
            context["prompt"] = run.child_prompt

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
