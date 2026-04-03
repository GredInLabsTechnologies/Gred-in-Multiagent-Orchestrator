from __future__ import annotations

import os
import re
from typing import Optional

from ...ops_models import ProviderEntry


_ENV_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)\}$")


class ProviderAuthService:
    """Administra credenciales y autenticacion de proveedores LLM."""
    @staticmethod
    def parse_env_ref(auth_ref: Optional[str]) -> Optional[str]:
        if not auth_ref:
            return None
        raw = str(auth_ref).strip()
        if raw.lower().startswith("env:"):
            env_name = raw.split(":", 1)[1].strip()
            return env_name or None
        return None

    @staticmethod
    def env_ref_from_name(env_name: str) -> str:
        return f"env:{env_name}"

    @staticmethod
    def resolve_env_expression(value: Optional[str]) -> Optional[str]:
        if not value:
            return value
        m = _ENV_PATTERN.match(value.strip())
        if not m:
            return value
        env_key = m.group(1)
        return os.environ.get(env_key)

    @classmethod
    def resolve_secret(cls, entry: ProviderEntry) -> Optional[str]:
        env_name = cls.parse_env_ref(entry.auth_ref)
        if env_name:
            # Check encrypted vault first (survives restarts)
            from .secret_store import get_secret
            stored = get_secret(env_name)
            if stored:
                return stored
            return os.environ.get(env_name)
        # Legacy fallback for migration compatibility
        return cls.resolve_env_expression(entry.api_key)

    @classmethod
    def sanitize_entry_for_storage(cls, provider_id: str, entry: ProviderEntry) -> ProviderEntry:
        auth_ref = entry.auth_ref
        auth_mode = (entry.auth_mode or "").strip() or None
        inline_key = (entry.api_key or "").strip()
        inline_account_ref = (auth_ref or "").strip()

        if inline_key and inline_key not in {"EMPTY", "***"}:
            env_match = _ENV_PATTERN.match(inline_key)
            if env_match:
                env_name = env_match.group(1)
            else:
                env_name = f"ORCH_PROVIDER_{provider_id.upper()}_API_KEY"
                os.environ[env_name] = inline_key
                from .secret_store import set_secret
                set_secret(env_name, inline_key)
            auth_ref = cls.env_ref_from_name(env_name)
            auth_mode = auth_mode or "api_key"

        if not auth_mode:
            auth_mode = "api_key" if auth_ref else "none"

        # Account mode may receive inline session/token through auth_ref.
        # Persist as env reference to avoid cleartext storage.
        if auth_mode == "account" and inline_account_ref and not inline_account_ref.lower().startswith("env:"):
            env_name = f"ORCH_PROVIDER_{provider_id.upper()}_ACCOUNT_TOKEN"
            os.environ[env_name] = inline_account_ref
            from .secret_store import set_secret
            set_secret(env_name, inline_account_ref)
            auth_ref = cls.env_ref_from_name(env_name)

        return entry.model_copy(
            update={
                "api_key": None,
                "auth_mode": auth_mode,
                "auth_ref": auth_ref,
            }
        )
