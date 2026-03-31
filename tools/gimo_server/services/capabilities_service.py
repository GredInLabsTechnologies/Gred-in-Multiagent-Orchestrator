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
        active_model, active_provider = None, None
        try:
            from .provider_service import ProviderService
            cfg = ProviderService.get_config()
            if cfg and cfg.active_provider:
                active_provider = cfg.active_provider
                provider_cfg = cfg.providers.get(active_provider)
                if provider_cfg:
                    active_model = provider_cfg.model
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

        # Timeout hints based on system load
        # Higher load → more generous timeouts to avoid false failures
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
            ],
            "active_model": active_model,
            "active_provider": active_provider,
            "system_load": load_level,
            "hints": {
                "generation_timeout_s": gen_timeout,
                "default_timeout_s": 15,
                "stream_timeout_s": 0,  # no timeout for SSE streams
            },
            "service_health": {
                "mastery": mastery_health,
                "storage": storage_health,
                "generation": generation_health,
                "context": context_health,
                "run_worker": "ok" if run_worker_attached else "degraded",
            },
        }
