from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict

from ...ops_models import ProviderConfig

logger = logging.getLogger("orchestrator.provider_state")


class ProviderStateService:
    """Controla el estado online/offline y salud de los proveedores LLM."""
    @staticmethod
    def _safe_auth_ref(auth_ref: str | None) -> str | None:
        if not auth_ref:
            return None
        raw = str(auth_ref).strip()
        if raw.lower().startswith("env:"):
            # env var name is acceptable metadata, not the secret value
            return raw
        # For vault/custom refs keep snapshot non-sensitive
        return "***"

    @staticmethod
    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def build_effective_state_snapshot(
        cls,
        cfg: ProviderConfig,
        normalize_provider_type: Callable[[str | None], str],
    ) -> Dict[str, Any]:
        active_entry = cfg.providers.get(cfg.active)
        if not active_entry:
            return {"active": cfg.active}
        return {
            "active": cfg.active,
            "provider_type": normalize_provider_type(active_entry.provider_type or active_entry.type),
            "model_id": active_entry.model_id or active_entry.model,
            "auth_mode": active_entry.auth_mode,
            "auth_ref": cls._safe_auth_ref(active_entry.auth_ref),
            "base_url": active_entry.base_url,
            "display_name": active_entry.display_name,
        }

    @classmethod
    def hydrate_v2_fields(
        cls,
        cfg: ProviderConfig,
        normalize_provider_type: Callable[[str | None], str],
    ) -> ProviderConfig:
        existing_effective_state = dict(cfg.effective_state or {})
        active_entry = cfg.providers.get(cfg.active)
        if active_entry:
            cfg.provider_type = normalize_provider_type(active_entry.provider_type or active_entry.type)
            cfg.model_id = active_entry.model_id or active_entry.model
            cfg.auth_mode = active_entry.auth_mode
            cfg.auth_ref = active_entry.auth_ref
            cfg.capabilities_snapshot = dict(active_entry.capabilities or {})
        # Restore secrets from encrypted vault on boot
        cls._restore_secrets_from_vault(cfg)

        if not cfg.last_validated_at:
            cfg.last_validated_at = cls.utc_now_iso()
        base_snapshot = cls.build_effective_state_snapshot(cfg, normalize_provider_type)
        # Preserve non-sensitive runtime status fields (health, actionable errors, warnings, etc.)
        cfg.effective_state = {**existing_effective_state, **base_snapshot}
        return cfg

    @classmethod
    def _restore_secrets_from_vault(cls, cfg: ProviderConfig) -> None:
        """On boot: restore secrets from encrypted vault to os.environ."""
        from .auth_service import ProviderAuthService
        from .secret_store import get_secret

        for pid, entry in cfg.providers.items():
            env_name = ProviderAuthService.parse_env_ref(entry.auth_ref)
            if env_name and not os.environ.get(env_name):
                stored = get_secret(env_name)
                if stored:
                    os.environ[env_name] = stored
                    logger.info("Restored credential for '%s' from vault", pid)
                else:
                    logger.warning(
                        "Provider '%s' needs re-auth: gimo providers set %s --api-key <key>",
                        pid, pid,
                    )
