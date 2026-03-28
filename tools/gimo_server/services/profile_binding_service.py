from __future__ import annotations

from dataclasses import dataclass

from ..models.agent_routing import TaskConstraints
from ..models.agent_routing import TaskDescriptor
from ..models.plan import PlanNodeBinding
from .model_router_service import ModelRouterService
from .provider_service_impl import ProviderService
from .provider_topology_service import ProviderTopologyService


@dataclass(frozen=True)
class BindingResolution:
    binding: PlanNodeBinding
    reason: str = ""
    candidate_count: int = 0


class ProfileBindingService:
    @classmethod
    def _binding_mode_within_constraints(
        cls,
        *,
        binding_mode: str,
        constraints: TaskConstraints | None,
    ) -> str:
        if not constraints or not constraints.allowed_binding_modes:
            return binding_mode
        return binding_mode if binding_mode in constraints.allowed_binding_modes else constraints.allowed_binding_modes[0]

    @classmethod
    def _resolve_constrained_binding(
        cls,
        *,
        descriptor: TaskDescriptor | None,
        requested_provider: str | None,
        requested_model: str | None,
        constraints: TaskConstraints,
    ) -> BindingResolution | None:
        candidates = list(constraints.allowed_bindings or [])
        if not candidates:
            return None
        decision = ModelRouterService.choose_binding_from_candidates(
            task_type=descriptor.task_type if descriptor else "default",
            candidates=candidates,
            requested_provider=requested_provider,
            requested_model=requested_model,
        )
        return BindingResolution(
            binding=PlanNodeBinding(
                provider=decision.provider_id,
                model=decision.model,
                binding_mode="plan_time",
            ),
            reason=decision.reason,
            candidate_count=1 + len(decision.alternatives),
        )

    @classmethod
    def _resolve_topology_binding(
        cls,
        *,
        descriptor: TaskDescriptor | None,
        requested_provider: str | None,
        requested_model: str | None,
    ) -> BindingResolution | None:
        cfg = ProviderService.get_config()
        if not cfg or not cfg.providers:
            return None

        roles = ProviderTopologyService.normalize_roles(cfg, dict(cfg.providers or {}))
        candidates = [roles.orchestrator, *list(roles.workers or [])]
        decision = ModelRouterService.choose_binding_from_candidates(
            task_type=descriptor.task_type if descriptor else "default",
            candidates=candidates,
            requested_provider=requested_provider,
            requested_model=requested_model,
        )
        return BindingResolution(
            binding=PlanNodeBinding(
                provider=decision.provider_id,
                model=decision.model,
                binding_mode="plan_time",
            ),
            reason=decision.reason,
            candidate_count=1 + len(decision.alternatives),
        )

    @classmethod
    def resolve_binding_decision(
        cls,
        *,
        descriptor: TaskDescriptor | None = None,
        requested_provider: str | None = None,
        requested_model: str | None = None,
        binding_mode: str = "plan_time",
        constraints: TaskConstraints | None = None,
    ) -> BindingResolution:
        binding_mode = cls._binding_mode_within_constraints(binding_mode=binding_mode, constraints=constraints)
        if constraints is not None:
            if not constraints.allowed_bindings:
                raise ValueError("Constraint compiler returned no allowed bindings")
            constrained = cls._resolve_constrained_binding(
                descriptor=descriptor,
                requested_provider=requested_provider,
                requested_model=requested_model,
                constraints=constraints,
            )
            if constrained is not None:
                return BindingResolution(
                    binding=constrained.binding.model_copy(update={"binding_mode": binding_mode}),
                    reason=constrained.reason,
                    candidate_count=constrained.candidate_count,
                )

        topology_binding = cls._resolve_topology_binding(
            descriptor=descriptor,
            requested_provider=requested_provider,
            requested_model=requested_model,
        )
        if topology_binding is not None:
            return BindingResolution(
                binding=topology_binding.binding.model_copy(update={"binding_mode": binding_mode}),
                reason=topology_binding.reason,
                candidate_count=topology_binding.candidate_count,
            )

        provider = str(requested_provider or "auto").strip() or "auto"
        model = str(requested_model or "auto").strip() or "auto"
        return BindingResolution(
            binding=PlanNodeBinding(provider=provider, model=model, binding_mode=binding_mode),
            reason="objective=constraints>success>quality>latency>cost|fallback=explicit_or_auto",
            candidate_count=1,
        )

    @classmethod
    def resolve_binding(
        cls,
        *,
        descriptor: TaskDescriptor | None = None,
        requested_provider: str | None = None,
        requested_model: str | None = None,
        binding_mode: str = "plan_time",
        constraints: TaskConstraints | None = None,
    ) -> PlanNodeBinding:
        return cls.resolve_binding_decision(
            descriptor=descriptor,
            requested_provider=requested_provider,
            requested_model=requested_model,
            binding_mode=binding_mode,
            constraints=constraints,
        ).binding
