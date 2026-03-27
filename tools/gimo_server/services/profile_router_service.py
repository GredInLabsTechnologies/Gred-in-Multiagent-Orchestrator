from __future__ import annotations

from ..models.agent_routing import RoutingDecision, RoutingDecisionSummary, TaskConstraints, TaskDescriptor
from .agent_catalog_service import AgentCatalogService, PRESET_CATALOG
from .execution_policy_service import LEGACY_MOOD_TO_POLICY


class ProfileRouterService:
    @classmethod
    def _select_preset_name(cls, descriptor: TaskDescriptor, requested_preset: str | None, legacy_mood: str | None) -> str:
        if requested_preset:
            AgentCatalogService.get_preset(requested_preset)
            return requested_preset
        if legacy_mood:
            return AgentCatalogService.preset_for_legacy_mood(legacy_mood)
        if descriptor.task_semantic == "planning":
            return "plan_orchestrator"
        if descriptor.task_semantic == "research":
            return "researcher"
        if descriptor.task_semantic == "security":
            return "safety_reviewer"
        if descriptor.task_semantic == "review":
            return "reviewer"
        if descriptor.task_semantic == "approval":
            return "human_gate"
        return "executor"

    @classmethod
    def route(
        cls,
        *,
        descriptor: TaskDescriptor,
        constraints: TaskConstraints,
        requested_preset: str | None = None,
        legacy_mood: str | None = None,
    ) -> RoutingDecision:
        preset_name = cls._select_preset_name(descriptor, requested_preset, legacy_mood)
        preset = AgentCatalogService.get_preset(preset_name)
        execution_policy = preset.execution_policy
        if legacy_mood and legacy_mood in LEGACY_MOOD_TO_POLICY:
            candidate_policy = LEGACY_MOOD_TO_POLICY[legacy_mood]
            if candidate_policy in constraints.allowed_policies:
                execution_policy = candidate_policy
        if execution_policy not in constraints.allowed_policies:
            execution_policy = constraints.allowed_policies[0]

        workflow_phase = preset.workflow_phase
        if descriptor.task_semantic == "planning":
            workflow_phase = "planning"
        elif descriptor.task_semantic == "approval":
            workflow_phase = "awaiting_approval"
        elif descriptor.task_semantic in {"review", "security"}:
            workflow_phase = "reviewing"
        elif descriptor.mutation_mode == "workspace":
            workflow_phase = "executing"

        resolved = AgentCatalogService.resolve_profile(
            agent_preset=preset.name,
            legacy_mood=legacy_mood,
            workflow_phase=workflow_phase,
        )
        resolved = resolved.model_copy(update={"execution_policy": execution_policy})
        summary = RoutingDecisionSummary(
            agent_preset=resolved.agent_preset,
            task_role=resolved.task_role,
            mood=resolved.mood,
            execution_policy=resolved.execution_policy,
            workflow_phase=resolved.workflow_phase,
        )
        return RoutingDecision(
            summary=summary,
            resolved_profile=resolved,
            binding_mode=constraints.allowed_binding_modes[0],
            routing_reason=(
                f"Preset '{preset_name}' selected from task_semantic='{descriptor.task_semantic}' "
                f"within allowed policies {constraints.allowed_policies}"
            ),
            candidate_count=len(PRESET_CATALOG),
        )
