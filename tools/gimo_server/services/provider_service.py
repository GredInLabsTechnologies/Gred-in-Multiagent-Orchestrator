from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional

from ..config import OPS_DATA_DIR
from ..ops_models import ProviderConfig, ProviderEntry
from ..providers.base import ProviderAdapter
from ..providers.openai_compat import OpenAICompatAdapter

logger = logging.getLogger("orchestrator.ops.provider")


_ENV_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)\}$")


class ProviderService:
    CONFIG_FILE = OPS_DATA_DIR / "provider.json"

    @classmethod
    def ensure_default_config(cls) -> None:
        """Create provider.json template if missing."""
        OPS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        if cls.CONFIG_FILE.exists():
            return
        default = ProviderConfig(
            active="local_ollama",
            providers={
                "local_ollama": ProviderEntry(
                    type="openai_compat",
                    base_url="http://localhost:11434/v1",
                    model="qwen2.5-coder:7b",
                    api_key=None,
                )
            },
        )
        cls.CONFIG_FILE.write_text(default.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def get_config(cls) -> Optional[ProviderConfig]:
        cls.ensure_default_config()
        try:
            return ProviderConfig.model_validate_json(cls.CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load provider config: %s", exc)
            return None

    @classmethod
    def get_public_config(cls) -> Optional[ProviderConfig]:
        cfg = cls.get_config()
        if not cfg:
            return None
        # redact api_key
        redacted = {}
        for k, p in cfg.providers.items():
            redacted[k] = ProviderEntry(
                type=p.type,
                base_url=p.base_url,
                api_key=None,
                model=p.model,
            )
        return ProviderConfig(active=cfg.active, providers=redacted)

    @classmethod
    def set_active(cls, active: str) -> ProviderConfig:
        cfg = cls.get_config()
        if not cfg:
            raise ValueError("Provider config missing")
        if active not in cfg.providers:
            raise ValueError(f"Unknown provider: {active}")
        cfg.active = active
        cls.CONFIG_FILE.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
        return cfg

    @classmethod
    def set_config(cls, cfg: ProviderConfig) -> ProviderConfig:
        OPS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.CONFIG_FILE.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
        return cfg

    @staticmethod
    def _resolve_env(value: Optional[str]) -> Optional[str]:
        if not value:
            return value
        m = _ENV_PATTERN.match(value.strip())
        if not m:
            return value
        env_key = m.group(1)
        return os.environ.get(env_key)

    @classmethod
    def _build_adapter(cls, cfg: ProviderConfig) -> ProviderAdapter:
        active = cfg.active
        if active not in cfg.providers:
            raise ValueError(f"Active provider not found in config: {active}")
        entry = cfg.providers[active]
        if entry.type == "openai_compat":
            if not entry.base_url:
                raise ValueError("openai_compat provider missing base_url")
            return OpenAICompatAdapter(
                base_url=entry.base_url,
                model=entry.model,
                api_key=cls._resolve_env(entry.api_key),
            )

        raise ValueError(f"Unsupported provider type: {entry.type}")

    @classmethod
    async def generate(cls, prompt: str, context: Dict[str, Any]) -> tuple[str, str]:
        """Generate content. Returns (provider_name, content)."""
        cfg = cls.get_config()
        if not cfg:
            raise ValueError("Provider config missing")
        adapter = cls._build_adapter(cfg)
        content = await adapter.generate(prompt, context)
        return cfg.active, content

    @classmethod
    async def health_check(cls) -> bool:
        cfg = cls.get_config()
        if not cfg:
            return False
        try:
            adapter = cls._build_adapter(cfg)
            return await adapter.health_check()
        except Exception:
            return False
