from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..config import OPS_DATA_DIR
from ..ops_models import McpServerConfig, ProviderConfig, ProviderEntry
from ..providers.base import ProviderAdapter
from ..providers.openai_compat import OpenAICompatAdapter
from .provider_capability_service import ProviderCapabilityService
from .provider_connector_service import ProviderConnectorService
from .provider_auth_service import ProviderAuthService
from .provider_state_service import ProviderStateService
from ...llm_security.cache import NormalizedLLMCache

logger = logging.getLogger("orchestrator.ops.provider")

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
                    provider_type="ollama_local",
                    display_name="Ollama Local",
                    base_url="http://localhost:11434/v1",
                    model="qwen2.5-coder:3b",
                    model_id="qwen2.5-coder:3b",
                    api_key=None,
                    capabilities=cls.capabilities_for("ollama_local"),
                )
            },
        )
        cls.CONFIG_FILE.write_text(default.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def normalize_provider_type(cls, raw_type: Optional[str]) -> str:
        return ProviderCapabilityService.normalize_provider_type(raw_type)

    @classmethod
    def capabilities_for(cls, provider_type: Optional[str]) -> Dict[str, Any]:
        return ProviderCapabilityService.capabilities_for(provider_type)

    @classmethod
    def get_capability_matrix(cls) -> Dict[str, Dict[str, Any]]:
        return ProviderCapabilityService.get_capability_matrix()

    @classmethod
    def _normalize_provider_entry(cls, entry: ProviderEntry) -> ProviderEntry:
        canonical_type = cls.normalize_provider_type(entry.provider_type or entry.type)
        inferred_local_ollama = False
        # Heuristic bridge: legacy openai_compat entries pointing to local Ollama runtime
        # should be treated as ollama_local to keep effective state and capabilities consistent.
        if canonical_type == "custom_openai_compatible":
            base_url = (entry.base_url or "").lower()
            if "localhost:11434" in base_url or "127.0.0.1:11434" in base_url:
                canonical_type = "ollama_local"
                inferred_local_ollama = True
        merged_capabilities = cls.capabilities_for(canonical_type)
        if entry.capabilities and not inferred_local_ollama:
            merged_capabilities.update(entry.capabilities)
        return ProviderEntry(
            type=entry.type,
            provider_type=canonical_type,
            display_name=entry.display_name,
            base_url=entry.base_url,
            api_key=entry.api_key,
            auth_mode=entry.auth_mode,
            auth_ref=entry.auth_ref,
            model=entry.model,
            model_id=entry.model_id,
            capabilities=merged_capabilities,
        )

    @classmethod
    def _normalize_config(cls, cfg: ProviderConfig) -> ProviderConfig:
        normalized: Dict[str, ProviderEntry] = {}
        for pid, entry in cfg.providers.items():
            normalized_entry = cls._normalize_provider_entry(entry)
            normalized[pid] = ProviderAuthService.sanitize_entry_for_storage(pid, normalized_entry)

        normalized_cfg = ProviderConfig(
            schema_version=2,
            active=cfg.active,
            providers=normalized,
            mcp_servers=cfg.mcp_servers,
            provider_type=cfg.provider_type,
            model_id=cfg.model_id,
            auth_mode=cfg.auth_mode,
            auth_ref=cfg.auth_ref,
            last_validated_at=cfg.last_validated_at,
            effective_state=dict(cfg.effective_state or {}),
            capabilities_snapshot=dict(cfg.capabilities_snapshot or {}),
        )

        return ProviderStateService.hydrate_v2_fields(normalized_cfg, cls.normalize_provider_type)

    @classmethod
    def get_config(cls) -> Optional[ProviderConfig]:
        cls.ensure_default_config()
        try:
            content = cls.CONFIG_FILE.read_text(encoding="utf-8").lstrip('\ufeff')
            cfg = ProviderConfig.model_validate_json(content)
            normalized_cfg = cls._normalize_config(cfg)
            if normalized_cfg.model_dump() != cfg.model_dump():
                cls.CONFIG_FILE.write_text(normalized_cfg.model_dump_json(indent=2), encoding="utf-8")
            return normalized_cfg
        except Exception as exc:
            logger.error(f"Failed to load provider config from {cls.CONFIG_FILE}: {exc}", exc_info=True)
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
                provider_type=p.provider_type,
                display_name=p.display_name,
                base_url=p.base_url,
                api_key=None,
                auth_mode=p.auth_mode,
                auth_ref=p.auth_ref,
                model=p.model,
                model_id=p.model_id,
                capabilities=dict(p.capabilities or {}),
            )
        redacted_mcp_servers = {}
        for name, srv in cfg.mcp_servers.items():
            redacted_mcp_servers[name] = McpServerConfig(
                command=srv.command,
                args=srv.args,
                env={k: "***" for k in srv.env.keys()},
                enabled=srv.enabled,
            )
        return ProviderConfig(
            schema_version=cfg.schema_version,
            active=cfg.active,
            providers=redacted,
            mcp_servers=redacted_mcp_servers,
            provider_type=cfg.provider_type,
            model_id=cfg.model_id,
            auth_mode=cfg.auth_mode,
            auth_ref=cfg.auth_ref,
            last_validated_at=cfg.last_validated_at,
            effective_state=dict(cfg.effective_state or {}),
            capabilities_snapshot=dict(cfg.capabilities_snapshot or {}),
        )

    @classmethod
    def set_active(cls, active: str) -> ProviderConfig:
        cfg = cls.get_config()
        if not cfg:
            raise ValueError("Provider config missing")
        if active not in cfg.providers:
            raise ValueError(f"Unknown provider: {active}")
        cfg.active = active
        normalized_cfg = cls._normalize_config(cfg)
        cls.CONFIG_FILE.write_text(normalized_cfg.model_dump_json(indent=2), encoding="utf-8")
        return normalized_cfg

    @classmethod
    def set_config(cls, cfg: ProviderConfig) -> ProviderConfig:
        OPS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        before = cls.get_config()
        normalized_cfg = cls._normalize_config(cfg)
        cls.CONFIG_FILE.write_text(normalized_cfg.model_dump_json(indent=2), encoding="utf-8")
        try:
            from .provider_catalog_service import ProviderCatalogService

            changed_types: set[str] = set()
            if before:
                all_ids = set(before.providers.keys()) | set(normalized_cfg.providers.keys())
                for pid in all_ids:
                    prev = before.providers.get(pid)
                    cur = normalized_cfg.providers.get(pid)
                    prev_type = cls.normalize_provider_type((prev.provider_type if prev else None) or (prev.type if prev else None)) if prev else None
                    cur_type = cls.normalize_provider_type((cur.provider_type if cur else None) or (cur.type if cur else None)) if cur else None
                    if prev_type:
                        changed_types.add(prev_type)
                    if cur_type:
                        changed_types.add(cur_type)
                    if prev and cur and (prev.auth_ref != cur.auth_ref or prev.auth_mode != cur.auth_mode):
                        if cur_type:
                            ProviderCatalogService.invalidate_cache(provider_type=cur_type, reason="credentials_changed")
            else:
                for entry in normalized_cfg.providers.values():
                    changed_types.add(cls.normalize_provider_type(entry.provider_type or entry.type))

            # conservative safety net for first persist / broad changes
            for ctype in changed_types:
                ProviderCatalogService.invalidate_cache(provider_type=ctype, reason="provider_config_updated")
        except Exception:
            # cache invalidation should never block config persistence
            pass
        return normalized_cfg

    @classmethod
    def record_validation(
        cls,
        *,
        provider_type: str,
        effective_model: Optional[str],
    ) -> Optional[ProviderConfig]:
        return cls.record_validation_result(
            provider_type=provider_type,
            valid=True,
            health="ok",
            effective_model=effective_model,
            error_actionable=None,
            warnings=[],
        )

    @classmethod
    def record_validation_result(
        cls,
        *,
        provider_type: str,
        valid: bool,
        health: str,
        effective_model: Optional[str],
        error_actionable: Optional[str],
        warnings: list[str] | None = None,
    ) -> Optional[ProviderConfig]:
        cfg = cls.get_config()
        if not cfg:
            return None
        canonical = cls.normalize_provider_type(provider_type)
        provider_id = None
        for pid, entry in cfg.providers.items():
            etype = cls.normalize_provider_type(entry.provider_type or entry.type)
            if etype == canonical:
                provider_id = pid
                break
        if provider_id is None:
            provider_id = cfg.active
        active = cfg.providers.get(provider_id)
        if not active:
            return cfg
        cfg.active = provider_id
        cfg.provider_type = canonical
        cfg.model_id = effective_model or active.model_id or active.model
        cfg.auth_mode = active.auth_mode
        cfg.auth_ref = active.auth_ref
        cfg.last_validated_at = ProviderStateService.utc_now_iso()
        cfg.capabilities_snapshot = dict(active.capabilities or {})
        cfg.effective_state = ProviderStateService.build_effective_state_snapshot(cfg, cls.normalize_provider_type)
        cfg.effective_state.update(
            {
                "valid": bool(valid),
                "health": health,
                "effective_model": cfg.model_id,
                "last_error_actionable": error_actionable,
                "warnings": list(warnings or []),
            }
        )
        cls.CONFIG_FILE.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
        return cfg

    @classmethod
    def _build_adapter(cls, cfg: ProviderConfig) -> ProviderAdapter:
        active = cfg.active
        if active not in cfg.providers:
            raise ValueError(f"Active provider not found in config: {active}")
        entry = cfg.providers[active]
        canonical_type = cls.normalize_provider_type(entry.provider_type or entry.type)
        if canonical_type in {"custom_openai_compatible", "ollama_local", "openai", "groq", "openrouter", "codex"}:
            if not entry.base_url:
                # For API providers without explicit base_url, keep backwards-safe default.
                if canonical_type == "openai":
                    base_url = "https://api.openai.com/v1"
                else:
                    raise ValueError(f"{canonical_type} provider missing base_url")
            else:
                base_url = entry.base_url
            return OpenAICompatAdapter(
                base_url=base_url,
                model=entry.model,
                api_key=ProviderAuthService.resolve_secret(entry),
            )

        raise ValueError(f"Unsupported provider type: {entry.type}")

    async def generate(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate content. Returns a rich dict with metrics."""
        return await self.__class__.static_generate(prompt, context)

    _cache_instance: Optional[NormalizedLLMCache] = None

    @classmethod
    def _get_cache(cls, ttl_hours: int = 24) -> NormalizedLLMCache:
        if cls._cache_instance is None:
            cache_dir = OPS_DATA_DIR / "cache" / "llm_responses"
            cls._cache_instance = NormalizedLLMCache(cache_dir, ttl_hours=ttl_hours)
        else:
            cls._cache_instance.ttl_hours = ttl_hours
        return cls._cache_instance

    @classmethod
    async def static_generate(cls, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Static version of generate for legacy/class-level calls."""
        from .cost_service import CostService
        from .ops_service import OpsService
        
        cfg = cls.get_config()
        if not cfg:
            raise ValueError("Provider config missing")
            
        # Load economy config
        economy = OpsService.get_config().economy
        
        # Prioritize model from context if provided (Cascade override)
        requested_model = context.get("model") or context.get("selected_model")
        
        # Determine task type for caching
        task_type = context.get("task_type", "default")
        
        # 1. OPT-IN CACHE CHECK
        if economy.cache_enabled:
            cache = cls._get_cache(ttl_hours=economy.cache_ttl_hours)
            cached_result = cache.get(prompt, task_type)
            if cached_result:
                model_name = requested_model or cfg.providers[cfg.active].model
                logger.info("Cache hit for task_type='%s' (model='%s')", task_type, model_name)
                return {
                    "provider": cfg.active,
                    "model": model_name,
                    "content": cached_result["result"],
                    "tokens_used": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": 0.0,
                    "cache_hit": True,
                    "usage": cached_result.get("metadata", {}).get("usage", {}),
                    "metadata": cached_result.get("metadata", {})
                }
        
        adapter = cls._build_adapter(cfg)
        
        # If a specific model is requested, try to use it if the provider supports it
        # Note: We still use the active provider adapter, but can tell it which model to use.
        if requested_model:
             context["model"] = requested_model # Ensure adapter sees it
             
        response = await adapter.generate(prompt, context)
        
        content = response["content"]
        usage = response.get("usage", {})
        prompt_t = usage.get("prompt_tokens", 0)
        completion_t = usage.get("completion_tokens", 0)
        total_t = prompt_t + completion_t
        
        # Determine model for pricing (use requested if available, else adapter default)
        model_name = requested_model or getattr(adapter, "model", cfg.providers[cfg.active].model)
        cost_usd = CostService.calculate_cost(model_name, prompt_t, completion_t)
        
        result = {
            "provider": cfg.active,
            "model": model_name,
            "content": content,
            "tokens_used": total_t,
            "prompt_tokens": prompt_t,
            "completion_tokens": completion_t,
            "cost_usd": cost_usd,
            "cache_hit": False
        }

        # 2. CACHE RESULT IF ENABLED
        if economy.cache_enabled:
            cache = cls._get_cache(ttl_hours=economy.cache_ttl_hours)
            cache.set(prompt, task_type, {
                "success": True,
                "response": content,
                "metadata": {
                    "usage": usage,
                    "model": model_name,
                    "provider": cfg.active
                }
            })

        return result

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

    @classmethod
    async def provider_health(cls, provider_id: str) -> bool:
        cfg = cls.get_config()
        if not cfg or provider_id not in cfg.providers:
            raise ValueError(f"Unknown provider: {provider_id}")
        try:
            scoped_cfg = ProviderConfig(
                active=provider_id,
                providers=cfg.providers,
                mcp_servers=cfg.mcp_servers,
            )
            adapter = cls._build_adapter(scoped_cfg)
            return await adapter.health_check()
        except Exception:
            return False

    @classmethod
    def list_connectors(cls) -> Dict[str, Any]:
        return ProviderConnectorService.list_connectors(cls)

    @classmethod
    async def connector_health(cls, connector_id: str, provider_id: Optional[str] = None) -> Dict[str, Any]:
        return await ProviderConnectorService.connector_health(cls, connector_id, provider_id)
