from __future__ import annotations

from ..models.agent_routing import RoutingDecision, RoutingDecisionSummary, TaskConstraints, TaskDescriptor, ModelBinding
from .agent_catalog_service import AgentCatalogService, PRESET_CATALOG


class ProfileRouterService:
    _SEMANTIC_PRIORS: dict[str, dict[str, float]] = {
        "planning": {"plan_orchestrator": 0.45, "researcher": 0.1},
        "research": {"researcher": 0.45, "reviewer": 0.1},
        "security": {"safety_reviewer": 0.45, "reviewer": 0.2},
        "review": {"reviewer": 0.45, "safety_reviewer": 0.3},
        "approval": {"human_gate": 0.45, "plan_orchestrator": 0.15},
        "implementation": {"executor": 0.45, "reviewer": 0.05},
    }

    @classmethod
    def _default_preset_name(cls, descriptor: TaskDescriptor) -> str:
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
    def _allowed_presets(cls, constraints: TaskConstraints) -> list[str]:
        """Returns presets compatible with constraints, excluding downgraded.

        P9: Filtra presets con failure_streak ≥ 5 (auto-downgrade).
        """
        from .anomaly_detection_service import AnomalyDetectionService

        # Get downgrade list
        downgraded = AnomalyDetectionService.get_downgrade_list()

        return [
            preset.name
            for preset in PRESET_CATALOG.values()
            if preset.execution_policy in constraints.allowed_policies
            and preset.name not in downgraded  # P9: Exclude downgraded
        ]

    @classmethod
    def _gics_advisory_adjustment(
        cls,
        *,
        descriptor: TaskDescriptor,
        preset_name: str,
    ) -> tuple[float, str]:
        """Calcula adjustment desde GICS advisory system (F8.2).

        Combina prior semántico hardcodeado con telemetría real para
        ranking adaptativo de presets.
        """
        from .advisory_engine import AdvisoryEngine

        task_semantic = descriptor.task_semantic

        # Obtener prior semántico hardcodeado
        prior_score = cls._SEMANTIC_PRIORS.get(task_semantic, {}).get(preset_name, 0.0)

        # Calcular score adaptativo desde telemetría
        adjustment, reason = AdvisoryEngine.get_preset_score(
            task_semantic=task_semantic,
            preset_name=preset_name,
            prior_score=prior_score,
        )

        return adjustment, reason

    @classmethod
    def _select_ranked_candidate(
        cls,
        descriptor: TaskDescriptor,
        constraints: TaskConstraints,
        requested_preset: str | None,
        legacy_mood: str | None,
    ) -> tuple[str, int, str]:
        valid_candidates = cls._allowed_presets(constraints)
        if not valid_candidates:
            raise ValueError("Constraint compiler did not yield any compatible preset candidates")

        requested_name = AgentCatalogService.get_preset(requested_preset).name if requested_preset else None
        legacy_name = AgentCatalogService.preset_for_legacy_mood(legacy_mood) if legacy_mood else None
        semantic_priors = cls._SEMANTIC_PRIORS.get(descriptor.task_semantic, {})

        ranked: list[tuple[tuple[float, float, float, float, str], str, str]] = []
        for preset_name in valid_candidates:
            requested_score = 1.0 if preset_name == requested_name else 0.0
            legacy_score = 0.6 if preset_name == legacy_name else 0.0
            semantic_score = float(semantic_priors.get(preset_name, 0.0))
            gics_score, gics_reason = cls._gics_advisory_adjustment(descriptor=descriptor, preset_name=preset_name)
            key = (
                requested_score,
                legacy_score,
                semantic_score,
                gics_score,
                preset_name,
            )
            reason = (
                f"candidate={preset_name}"
                f"|requested={requested_score:.2f}"
                f"|legacy={legacy_score:.2f}"
                f"|semantic={semantic_score:.2f}"
                f"|{gics_reason}"
            )
            ranked.append((key, preset_name, reason))

        ranked.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], -item[0][3], item[0][4]))
        _, selected_name, selected_reason = ranked[0]
        return selected_name, len(valid_candidates), selected_reason

    @classmethod
    def route(
        cls,
        *,
        descriptor: TaskDescriptor,
        constraints: TaskConstraints,
        requested_preset: str | None = None,
        requested_mood: str | None = None,
        legacy_mood: str | None = None,
    ) -> RoutingDecision:
        if not constraints.allowed_policies:
            raise ValueError("Constraint compiler returned no allowed execution policies")
        preset_name, candidate_count, candidate_reason = cls._select_ranked_candidate(
            descriptor,
            constraints,
            requested_preset,
            legacy_mood,
        )
        preset = AgentCatalogService.get_preset(preset_name)
        execution_policy = preset.execution_policy
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
            mood=requested_mood,
            legacy_mood=legacy_mood,
            workflow_phase=workflow_phase,
        )
        resolved = resolved.model_copy(update={"execution_policy": execution_policy})

        # Build binding (provider/model resolved later by ProfileBindingService)
        binding = ModelBinding(
            provider="auto",
            model="auto",
            binding_mode=(constraints.allowed_binding_modes[0] if constraints.allowed_binding_modes else "plan_time"),
            binding_reason="pending_binding_resolution"
        )

        return RoutingDecision(
            profile=resolved,
            binding=binding,
            routing_reason=(
                f"objective=constraints>requested>legacy>semantic>gics_advisory"
                f"|task_semantic={descriptor.task_semantic}"
                f"|allowed_policies={','.join(constraints.allowed_policies)}"
                f"|selected={preset_name}"
                f"|{candidate_reason}"
            ),
            candidate_count=candidate_count,
        )
