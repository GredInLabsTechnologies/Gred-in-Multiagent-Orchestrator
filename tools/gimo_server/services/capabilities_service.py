"""Server capabilities discovery service.

Provides operation contracts (timeouts, health, active model) to all surfaces.
This is the MANDATORY single source of truth for CLI, UI, and MCP.

Contract enforcement:
- ALL surfaces MUST call /ops/capabilities before operation
- Server-driven truth — clients never hardcode timeouts, health, or model selection
- One path, one contract, no parallel inferences
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request

from ..security.auth import SESSION_COOKIE_NAME, AuthContext, session_store
from ..version import __version__

logger = logging.getLogger("orchestrator.capabilities")


class CapabilitiesService:
    """Server capabilities discovery service."""

    @staticmethod
    async def get_capabilities(request: Request, auth: AuthContext) -> dict[str, Any]:
        """Get server capabilities with operation hints and service health.

        Returns:
            Capabilities contract with:
            - version: server version
            - role: authenticated user role
            - plan: subscription plan (local/standard/pro)
            - features: enabled features list
            - active_model: currently selected LLM model
            - active_provider: provider ID (ollama/anthropic/openai)
            - system_load: hardware load level (normal/caution/critical)
            - hints: operation timeout hints per category
            - service_health: per-service health status
        """
        # Plan (from Firebase session if exists)
        plan = "local"
        cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if cookie:
            session = session_store.validate(cookie)
            if session and session.plan:
                plan = session.plan

        # System load (from HardwareMonitorService)
        load_level = "safe"
        try:
            from .hardware_monitor_service import HardwareMonitorService
            hw = HardwareMonitorService.get_instance()
            load_level = hw.get_load_level()
        except Exception:
            logger.warning("HardwareMonitorService unavailable, defaulting to 'safe'")

        # Active model and provider (from ProviderService)
        # Uses same resolution as OperatorStatusService: canonical roles first, legacy fallback
        active_model, active_provider = None, None
        try:
            from .provider_service_impl import ProviderService
            cfg = ProviderService.get_config()
            if cfg:
                binding = cfg.primary_orchestrator_binding() if hasattr(cfg, "primary_orchestrator_binding") else None
                if binding:
                    active_provider = binding.provider_id
                    active_model = binding.model
                else:
                    active_provider = getattr(cfg, "active", None)
                    providers = getattr(cfg, "providers", None) or {}
                    active_entry = providers.get(active_provider) if active_provider else None
                    if active_entry:
                        active_model = active_entry.configured_model_id() if hasattr(active_entry, "configured_model_id") else getattr(active_entry, "model", None)
        except Exception:
            logger.warning("ProviderService unavailable, model info will be None")

        # Service health probes
        gics_attached = bool(getattr(request.app.state, "gics", None))
        run_worker_attached = bool(getattr(request.app.state, "run_worker", None))

        # Mastery depends on GICS (for cost storage)
        mastery_health = "ok" if gics_attached else "degraded"
        storage_health = "ok" if gics_attached else "unavailable"

        # Generation depends on ProviderService being configured
        generation_health = "ok" if active_provider else "degraded"

        # Context/IDE features are always ok (no hard dependencies)
        context_health = "ok"

        # GAEP Phase 2: Adaptive timeout prediction based on historical data
        try:
            from .timeout.adaptive_timeout_service import AdaptiveTimeoutService

            # Inject GICS for historical data access
            gics = getattr(request.app.state, "gics", None)
            if gics:
                AdaptiveTimeoutService.set_gics(gics)

            # Predict timeout for plan generation with context
            gen_timeout = AdaptiveTimeoutService.predict_timeout(
                operation="plan",
                context={
                    "model": active_model,
                    "system_load": load_level,
                }
            )

            logger.debug(
                "Adaptive timeout for plan generation: %.1fs (model=%s, load=%s)",
                gen_timeout, active_model, load_level
            )

        except Exception as exc:
            # Fallback to static timeouts if predictor fails
            logger.warning("Adaptive timeout prediction failed, using static fallback: %s", exc)
            if load_level == "critical":
                gen_timeout = 300  # 5 min under critical load
            elif load_level == "caution":
                gen_timeout = 240  # 4 min under caution
            else:  # "safe" or unknown
                gen_timeout = 120  # 2 min under safe/normal load

        return {
            "version": __version__,
            "role": auth.role,
            "plan": plan,
            "features": [
                "plans",
                "runs",
                "chat",
                "threads",
                "mastery",
                "trust",
                "observe",
                "plan_streaming",  # SEA Phase 3: SSE progress streaming
            ],
            "active_model": active_model,
            "active_provider": active_provider,
            "system_load": load_level,
            "hints": {
                "generation_timeout_s": gen_timeout,
                "default_timeout_s": 30,
                "stream_timeout_s": 0,  # no timeout for SSE streams
                "operation_timeouts": {
                    "/approve": gen_timeout,
                    "/execute": gen_timeout,
                    "/chat": 0,
                    "/stream": 0,
                    "/events": 0,
                    "/generate": gen_timeout,
                    "/merge": 60,
                    "/mastery": 30,
                    "/observability": 30,
                    "/trust": 30,
                },
            },
            "service_health": {
                "mastery": mastery_health,
                "storage": storage_health,
                "generation": generation_health,
                "context": context_health,
                "run_worker": "ok" if run_worker_attached else "degraded",
            },
        }
