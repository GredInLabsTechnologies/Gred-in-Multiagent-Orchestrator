from __future__ import annotations

from ..models.plan import PlanNodeBinding
from .provider_service_impl import ProviderService


class ProfileBindingService:
    @classmethod
    def resolve_binding(
        cls,
        *,
        requested_provider: str | None = None,
        requested_model: str | None = None,
        binding_mode: str = "plan_time",
    ) -> PlanNodeBinding:
        provider = str(requested_provider or "auto").strip() or "auto"
        model = str(requested_model or "auto").strip() or "auto"
        if provider != "auto" and model != "auto":
            return PlanNodeBinding(provider=provider, model=model, binding_mode=binding_mode)

        cfg = ProviderService.get_config()
        if not cfg or not cfg.roles:
            return PlanNodeBinding(provider=provider, model=model, binding_mode=binding_mode)

        binding = cfg.roles.orchestrator if provider == "auto" else None
        if binding is None and cfg.roles.workers:
            binding = cfg.roles.workers[0]
        if binding is None:
            return PlanNodeBinding(provider=provider, model=model, binding_mode=binding_mode)
        return PlanNodeBinding(
            provider=provider if provider != "auto" else binding.provider_id,
            model=model if model != "auto" else binding.model,
            binding_mode=binding_mode,  # type: ignore[arg-type]
        )
