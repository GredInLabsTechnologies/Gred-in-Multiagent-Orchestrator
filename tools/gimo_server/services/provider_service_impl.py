from __future__ import annotations

import asyncio
import logging
import json
import time
import shutil
from typing import Any, Dict, Optional

from ..config import OPS_DATA_DIR
from ..ops_models import (
    McpServerConfig,
    ProviderConfig,
    ProviderEntry,
    ProviderRoleBinding,
    ProviderRolesConfig,
)
from ..providers.base import ProviderAdapter
from .provider_capability_service import ProviderCapabilityService
from .provider_connector_service import ProviderConnectorService
from .provider_auth_service import ProviderAuthService
from .provider_state_service import ProviderStateService
from .provider_service_adapter_registry import build_provider_adapter
from .provider_config_change_service import ProviderConfigChangeService
from .provider_topology_service import ProviderTopologyService
from .llm_cache import NormalizedLLMCache
from .model_router_service import ModelRouterService
from .observability_service import ObservabilityService

logger = logging.getLogger("orchestrator.ops.provider")

class ProviderService:
    """Punto de entrada unificado para interactuar y enviar prompts a LLMs."""
    CONFIG_FILE = OPS_DATA_DIR / "provider.json"

    @classmethod
    def ensure_default_config(cls) -> None:
        """Create provider.json template if missing.

        Priority: codex CLI (if installed) → claude CLI (if installed) → empty config.
        Never default to Ollama — the user may not have it installed.
        """
        import shutil as _shutil
        OPS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        if cls.CONFIG_FILE.exists():
            return

        providers: dict = {}
        active: str = ""
        orch_model: str = ""

        if _shutil.which("codex") is not None:
            providers["codex-account"] = ProviderEntry(
                type="codex",
                provider_type="codex",
                display_name="Codex Account Mode",
                auth_mode="account",
                model="gpt-5-codex",
                model_id="gpt-5-codex",
                capabilities=cls.capabilities_for("codex"),
            )
            active = "codex-account"
            orch_model = "gpt-5-codex"

        if _shutil.which("claude") is not None:
            providers["claude-account"] = ProviderEntry(
                type="claude",
                provider_type="claude",
                display_name="Claude Account Mode",
                auth_mode="account",
                model="claude-3-7-sonnet-latest",
                model_id="claude-3-7-sonnet-latest",
                capabilities=cls.capabilities_for("claude"),
            )
            if not active:
                active = "claude-account"
                orch_model = "claude-3-7-sonnet-latest"

        roles = ProviderRolesConfig(
            orchestrator=ProviderRoleBinding(provider_id=active, model=orch_model) if active else None,
            workers=[],
        )
        default = ProviderConfig(active=active, providers=providers, roles=roles)
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
    def _has_account_mode_provider(cls, providers: Dict[str, ProviderEntry], provider_type: str) -> bool:
        return ProviderTopologyService.has_account_mode_provider(
            providers,
            provider_type,
            cls.normalize_provider_type,
        )

    @classmethod
    def _inject_cli_account_providers(cls, providers: Dict[str, ProviderEntry]) -> Dict[str, ProviderEntry]:
        """Auto-provision account-mode providers when local CLIs are available."""
        return ProviderTopologyService.inject_cli_account_providers(
            providers,
            normalize_provider_type=cls.normalize_provider_type,
            capabilities_for=cls.capabilities_for,
        )

    @classmethod
    def _normalize_config(cls, cfg: ProviderConfig) -> ProviderConfig:
        normalized: Dict[str, ProviderEntry] = {}
        for pid, entry in cfg.providers.items():
            normalized_entry = cls._normalize_provider_entry(entry)
            normalized[pid] = ProviderAuthService.sanitize_entry_for_storage(pid, normalized_entry)

        normalized = cls._inject_cli_account_providers(normalized)

        roles = cls._normalize_roles(cfg, normalized)

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
            roles=roles,
            orchestrator_provider=roles.orchestrator.provider_id,
            worker_provider=roles.workers[0].provider_id if roles.workers else None,
            orchestrator_model=roles.orchestrator.model,
            worker_model=roles.workers[0].model if roles.workers else None,
        )

        return ProviderStateService.hydrate_v2_fields(normalized_cfg, cls.normalize_provider_type)

    @classmethod
    def _get_entry_model(cls, provider_id: str, providers: Dict[str, ProviderEntry]) -> str:
        return ProviderTopologyService._get_entry_model(provider_id, providers)

    @classmethod
    def _create_binding(cls, provider_id: str, model: str | None, providers: Dict[str, ProviderEntry]) -> ProviderRoleBinding | None:
        return ProviderTopologyService._create_binding(provider_id, model, providers)

    @classmethod
    def _get_roles_from_schema(cls, cfg: ProviderConfig, providers: Dict[str, ProviderEntry]) -> tuple[ProviderRoleBinding | None, list[ProviderRoleBinding]]:
        return ProviderTopologyService._get_roles_from_schema(cfg, providers)

    @classmethod
    def _get_legacy_roles(cls, cfg: ProviderConfig, providers: Dict[str, ProviderEntry]) -> tuple[ProviderRoleBinding | None, list[ProviderRoleBinding]]:
        return ProviderTopologyService._get_legacy_roles(cfg, providers)

    @classmethod
    def _get_fallback_orchestrator(cls, cfg: ProviderConfig, providers: Dict[str, ProviderEntry]) -> ProviderRoleBinding | None:
        return ProviderTopologyService._get_fallback_orchestrator(cfg, providers)

    @classmethod
    def _deduplicate_workers(cls, orchestrator: ProviderRoleBinding | None, worker_bindings: list[ProviderRoleBinding]) -> list[ProviderRoleBinding]:
        return ProviderTopologyService._deduplicate_workers(orchestrator, worker_bindings)

    @classmethod
    def _normalize_roles(cls, cfg: ProviderConfig, providers: Dict[str, ProviderEntry]) -> ProviderRolesConfig:
        return ProviderTopologyService.normalize_roles(cfg, providers)

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
                env=dict.fromkeys(srv.env.keys(), "***"),
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
            roles=cfg.roles,
            orchestrator_provider=cfg.orchestrator_provider,
            worker_provider=cfg.worker_provider,
            orchestrator_model=cfg.orchestrator_model,
            worker_model=cfg.worker_model,
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
    def _get_changed_provider_types(cls, before: Optional[ProviderConfig], cur_cfg: ProviderConfig) -> set[str]:
        return ProviderConfigChangeService.get_changed_provider_types(
            before=before,
            current=cur_cfg,
            normalize_provider_type=cls.normalize_provider_type,
            invalidate_catalog_cache=cls._invalidate_catalog_cache,
        )

    @classmethod
    def _invalidate_catalog_cache(cls, provider_type: str, reason: str) -> None:
        from .provider_catalog_service import ProviderCatalogService

        ProviderCatalogService.invalidate_cache(provider_type=provider_type, reason=reason)

    @classmethod
    def _compare_provider(cls, prev, cur, changed_types: set[str]):
        ProviderConfigChangeService.compare_provider(
            prev=prev,
            cur=cur,
            changed_types=changed_types,
            normalize_provider_type=cls.normalize_provider_type,
            invalidate_catalog_cache=cls._invalidate_catalog_cache,
        )

    @classmethod
    def _invalidate_caches_on_config_change(cls, before: Optional[ProviderConfig], cur_cfg: ProviderConfig) -> None:
        try:
            changed_types = cls._get_changed_provider_types(before, cur_cfg)
            for ctype in changed_types:
                cls._invalidate_catalog_cache(provider_type=ctype, reason="provider_config_updated")
        except Exception:
            pass

    @classmethod
    def set_config(cls, cfg: ProviderConfig) -> ProviderConfig:
        OPS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        before = cls.get_config()
        normalized_cfg = cls._normalize_config(cfg)
        cls.CONFIG_FILE.write_text(normalized_cfg.model_dump_json(indent=2), encoding="utf-8")
        cls._invalidate_caches_on_config_change(before, normalized_cfg)
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
    def _build_adapter(cls, cfg: ProviderConfig, provider_id: Optional[str] = None) -> ProviderAdapter:
        active = provider_id or cfg.active
        if active not in cfg.providers:
            raise ValueError(f"Active provider not found in config: {active}")
        entry = cfg.providers[active]
        canonical_type = cls.normalize_provider_type(entry.provider_type or entry.type)
        return build_provider_adapter(
            entry=entry,
            canonical_type=canonical_type,
            resolve_secret=ProviderAuthService.resolve_secret,
        )

    @classmethod
    def _append_role_binding(
        cls, cfg: ProviderConfig, provider_id: str, model_id: str | None, out: list[tuple[str, str, str]]
    ) -> None:
        entry = cfg.providers.get(provider_id)
        if not entry:
            return
        model = str(model_id or entry.model_id or entry.model or "").strip()
        if not model:
            return
        ptype = cls.normalize_provider_type(entry.provider_type or entry.type)
        out.append((provider_id, ptype, model))

    @classmethod
    def _collect_role_bindings(cls, cfg: ProviderConfig, default_provider_id: str, default_model: str) -> list[tuple[str, str, str]]:
        """Collect candidate bindings for runtime model selection."""
        out: list[tuple[str, str, str]] = []
        cls._append_role_binding(cfg, default_provider_id, default_model, out)

        roles = getattr(cfg, "roles", None)
        if roles:
            orch = getattr(roles, "orchestrator", None)
            if orch:
                cls._append_role_binding(cfg, str(getattr(orch, "provider_id", "") or ""), getattr(orch, "model", None), out)
            for w in (getattr(roles, "workers", []) or []):
                cls._append_role_binding(cfg, str(getattr(w, "provider_id", "") or ""), getattr(w, "model", None), out)

        dedup: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for p_id, p_type, model in out:
            if (p_id, model) not in seen:
                seen.add((p_id, model))
                dedup.append((p_id, p_type, model))
        return dedup

    @classmethod
    def _select_runtime_binding_with_reliability(
        cls,
        cfg: ProviderConfig,
        *,
        provider_id: str,
        model_id: str,
    ) -> tuple[str, str]:
        """Pick a more reliable binding when GICS indicates anomaly/low confidence."""
        candidates = cls._collect_role_bindings(cfg, provider_id, model_id)
        if not candidates:
            return provider_id, model_id

        def _rel(ptype: str, model: str) -> tuple[float, bool]:
            from .ops_service import OpsService

            data = OpsService.get_model_reliability(provider_type=ptype, model_id=model) or {}
            score = float(data.get("score", 0.5) or 0.5)
            anomaly = bool(data.get("anomaly", False))
            return max(0.0, min(1.0, score)), anomaly

        current_provider_type = cls.normalize_provider_type(
            cfg.providers.get(provider_id).provider_type if cfg.providers.get(provider_id) else provider_id
        )
        current_score, current_anomaly = _rel(current_provider_type, model_id)
        if not current_anomaly and current_score >= 0.35:
            return provider_id, model_id

        best = (provider_id, model_id, current_score)
        for cand_provider, cand_type, cand_model in candidates:
            score, anomaly = _rel(cand_type, cand_model)
            if anomaly:
                continue
            if score > best[2]:
                best = (cand_provider, cand_model, score)

        return best[0], best[1]

    async def generate(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate content. Returns a rich dict with metrics."""
        return await self.__class__.static_generate(prompt, context)

    _cache_instance: Optional[NormalizedLLMCache] = None
    _FALLBACK_METRICS_FILE = OPS_DATA_DIR / "fallback_metrics.json"
    _FALLBACK_WINDOW_SECONDS = 3600

    @classmethod
    def _record_fallback_and_get_window_count(cls) -> int:
        """Track fallback events in a rolling time window (phase-6 metric)."""
        now = int(time.time())
        cutoff = now - cls._FALLBACK_WINDOW_SECONDS
        OPS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        events: list[int] = []
        try:
            if cls._FALLBACK_METRICS_FILE.exists():
                raw = json.loads(cls._FALLBACK_METRICS_FILE.read_text(encoding="utf-8") or "{}")
                events = [int(x) for x in (raw.get("events") or []) if int(x) >= cutoff]
        except Exception:
            events = []
        events.append(now)
        payload = {"window_seconds": cls._FALLBACK_WINDOW_SECONDS, "events": events}
        cls._FALLBACK_METRICS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(events)

    @classmethod
    def _get_cache(cls, ttl_hours: int = 24) -> NormalizedLLMCache:
        if cls._cache_instance is None:
            cache_dir = OPS_DATA_DIR / "cache" / "llm_responses"
            cls._cache_instance = NormalizedLLMCache(cache_dir, ttl_hours=ttl_hours)
        else:
            cls._cache_instance.ttl_hours = ttl_hours
        return cls._cache_instance

    @classmethod
    def _resolve_effective_provider_and_model(
        cls, cfg: ProviderConfig, context: Dict[str, Any], task_type: str
    ) -> tuple[str, str | None]:
        requested_model = context.get("model") or context.get("selected_model")
        effective_provider = cfg.active
        
        if not context.get("model"):
            tier_prov, tier_model = ModelRouterService.resolve_tier_routing(task_type, cfg)
            if tier_prov:
                effective_provider = tier_prov
                requested_model = tier_model or requested_model

        default_entry = cfg.providers.get(effective_provider)
        default_model = str(requested_model or (default_entry.model if default_entry else "") or "").strip()
        if default_model:
            effective_provider, requested_model = cls._select_runtime_binding_with_reliability(
                cfg, provider_id=effective_provider, model_id=default_model,
            )
        return effective_provider, requested_model

    @classmethod
    def _check_cache(
        cls, prompt: str, task_type: str, economy: Any, model_name: str, effective_provider: str
    ) -> Dict[str, Any] | None:
        if not economy.cache_enabled:
            return None
        cache = cls._get_cache(ttl_hours=economy.cache_ttl_hours)
        cached_result = cache.get(prompt, task_type)
        if cached_result:
            logger.info("Cache hit for task_type='%s' (model='%s')", task_type, model_name)
            return {
                "provider": effective_provider, "model": model_name,
                "content": cached_result["result"], "tokens_used": 0,
                "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
                "cache_hit": True, "usage": cached_result.get("metadata", {}).get("usage", {}),
                "metadata": cached_result.get("metadata", {})
            }
        return None
        
    @classmethod
    def _record_outcome_safe(
        cls, provider_type: str, model_id: str, success: bool, start_ts: float, cost_usd: float, task_type: str
    ) -> None:
        from .ops_service import OpsService
        try:
            OpsService.record_model_outcome(
                provider_type=provider_type, model_id=model_id, success=success,
                latency_ms=(time.perf_counter() - start_ts) * 1000.0, cost_usd=cost_usd, task_type=task_type,
            )
        except Exception:
            pass

    @classmethod
    async def static_generate(cls, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Static version of generate for legacy/class-level calls."""
        from .cost_service import CostService
        from .ops_service import OpsService
        
        cfg = cls.get_config()
        if not cfg:
            raise ValueError("Provider config missing")
            
        from ..models.economy import UserEconomyConfig
        economy = OpsService.get_config().economy or UserEconomyConfig()
        task_type = context.get("task_type", "default")
        
        effective_provider, requested_model = cls._resolve_effective_provider_and_model(cfg, context, task_type)

        model_name = requested_model or cfg.providers[effective_provider].model
        cached = cls._check_cache(prompt, task_type, economy, model_name, effective_provider)
        if cached:
            return cached
        
        adapter = cls._build_adapter(cfg, provider_id=effective_provider)
        if requested_model:
             context["model"] = requested_model
             
        start_ts = time.perf_counter()
        provider_entry = cfg.providers.get(effective_provider)
        provider_type = cls.normalize_provider_type(provider_entry.provider_type if provider_entry else effective_provider)
        
        try:
            response = await adapter.generate(prompt, context)
        except Exception:
            cls._record_outcome_safe(
                provider_type=provider_type,
                model_id=str(requested_model or getattr(adapter, "model", "unknown")),
                success=False, start_ts=start_ts, cost_usd=0.0, task_type=str(task_type)
            )
            raise
        
        usage = response.get("usage", {})
        prompt_t = usage.get("prompt_tokens", 0)
        completion_t = usage.get("completion_tokens", 0)
        
        model_name = requested_model or getattr(adapter, "model", cfg.providers[effective_provider].model)
        cost_usd = CostService.calculate_cost(model_name, prompt_t, completion_t)
        
        result = {
            "provider": effective_provider, "model": model_name,
            "content": response["content"], "tokens_used": prompt_t + completion_t,
            "prompt_tokens": prompt_t, "completion_tokens": completion_t,
            "cost_usd": cost_usd, "cache_hit": False
        }

        cls._record_outcome_safe(
            provider_type=provider_type, model_id=str(model_name),
            success=True, start_ts=start_ts, cost_usd=float(cost_usd or 0.0), task_type=str(task_type)
        )

        if economy.cache_enabled:
            cls._get_cache(ttl_hours=economy.cache_ttl_hours).set(prompt, task_type, {
                "success": True, "response": response["content"],
                "metadata": {"usage": usage, "model": model_name, "provider": effective_provider}
            })

        return result

    @classmethod
    async def _execute_phase6_primary(
        cls,
        prompt: str,
        safe_context: Dict[str, Any],
        decision: Any,
        started_at: float,
    ) -> tuple[Optional[Dict[str, Any]], Optional[Exception], str]:
        primary_model = ModelRouterService.PHASE6_PRIMARY_MODEL
        max_primary_attempts = 2
        backoff_seconds = 0.25
        last_error: Optional[Exception] = None
        last_reason = "unknown"

        for attempt in range(1, max_primary_attempts + 1):
            try:
                primary_result = await cls.static_generate(
                    prompt,
                    {**safe_context, "model": primary_model},
                )
                primary_result.update(
                    {
                        "strategy_decision_id": decision.strategy_decision_id,
                        "strategy_reason": "cloud_primary_selected",
                        "model_attempted": primary_model,
                        "failure_reason": "",
                        "final_model_used": primary_model,
                        "fallback_used": False,
                        "execution_decision": "PRIMARY_MODEL_SUCCESS",
                        "fallback_count_window": 0,
                    }
                )
                cls._record_phase65_ai_usage(
                    result=primary_result,
                    context=safe_context,
                    latency_ms=(time.perf_counter() - started_at) * 1000.0,
                    error_code="",
                )
                return primary_result, None, ""
            except Exception as exc:
                last_error = exc
                last_reason = ModelRouterService.classify_phase6_failure_reason(exc)
                if (
                    last_reason in ModelRouterService._PHASE6_FALLBACK_ALLOWED
                    and attempt < max_primary_attempts
                ):
                    await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
                    continue
                break
        
        return None, last_error, last_reason

    @classmethod
    async def static_generate_phase6_strategy(
        cls,
        *,
        prompt: str,
        context: Dict[str, Any],
        intent_effective: str,
        path_scope: list[str],
    ) -> Dict[str, Any]:
        """Phase-6 deterministic cloud/local strategy resolver execution.

        Rules:
        - Primary: qwen3-coder:480b-cloud
        - Fallback: qwen3:8b (local)
        - Fallback only on: 429, session/weekly limits, timeout, network error, 5xx
        - No fallback on: 400, policy/schema/merge-gate errors
        - SECURITY_CHANGE / CORE_RUNTIME_CHANGE / sensitive scope => local-only
        """

        safe_context = dict(context or {})
        started_at = time.perf_counter()
        decision = ModelRouterService.resolve_phase6_strategy(
            intent_effective=str(intent_effective or ""),
            path_scope=list(path_scope or []),
            primary_failure_reason="",
        )

        if decision.strategy_reason == "forced_local_only":
            local_result = await cls.static_generate(
                prompt,
                {**safe_context, "model": decision.final_model_used},
            )
            local_result.update(
                {
                    "strategy_decision_id": decision.strategy_decision_id,
                    "strategy_reason": decision.strategy_reason,
                    "model_attempted": decision.model_attempted,
                    "failure_reason": "",
                    "final_model_used": decision.final_model_used,
                    "fallback_used": False,
                    "execution_decision": "PRIMARY_MODEL_SUCCESS",
                    "fallback_count_window": 0,
                }
            )
            cls._record_phase65_ai_usage(
                result=local_result,
                context=safe_context,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                error_code="",
            )
            return local_result

        primary_result, last_error, last_reason = await cls._execute_phase6_primary(
            prompt, safe_context, decision, started_at
        )
        if primary_result:
            return primary_result

        fallback_model = ModelRouterService.PHASE6_FALLBACK_MODEL

        resolved = ModelRouterService.resolve_phase6_strategy(
            intent_effective=str(intent_effective or ""),
            path_scope=list(path_scope or []),
            primary_failure_reason=last_reason,
        )

        if not resolved.fallback_used:
            raise RuntimeError(f"PHASE6_NO_FALLBACK:{last_reason}") from last_error

        try:
            fallback_result = await cls.static_generate(
                prompt,
                {**safe_context, "model": fallback_model},
            )
        except Exception as fallback_exc:
            raise RuntimeError(f"PHASE6_FALLBACK_FAILED:{last_reason}") from fallback_exc

        fallback_result.update(
            {
                "strategy_decision_id": resolved.strategy_decision_id,
                "strategy_reason": resolved.strategy_reason,
                "model_attempted": resolved.model_attempted,
                "failure_reason": resolved.failure_reason,
                "final_model_used": resolved.final_model_used,
                "fallback_used": True,
                "execution_decision": "FALLBACK_MODEL_USED",
                "fallback_count_window": cls._record_fallback_and_get_window_count(),
            }
        )
        cls._record_phase65_ai_usage(
            result=fallback_result,
            context=safe_context,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            error_code=str(fallback_result.get("failure_reason") or ""),
        )
        return fallback_result

    @classmethod
    def _record_phase65_ai_usage(
        cls,
        *,
        result: Dict[str, Any],
        context: Dict[str, Any],
        latency_ms: float,
        error_code: str,
    ) -> None:
        """Best-effort AI usage telemetry required by Phase 6.5."""
        try:
            cfg = cls.get_config()
            provider_type = ""
            auth_mode = ""
            if cfg and cfg.active in cfg.providers:
                entry = cfg.providers[cfg.active]
                provider_type = str(entry.provider_type or entry.type or "")
                auth_mode = str(entry.auth_mode or "")

            ObservabilityService.record_ai_usage(
                run_id=str(context.get("run_id") or ""),
                draft_id=str(context.get("draft_id") or ""),
                provider_type=provider_type,
                auth_mode=auth_mode,
                model=str(result.get("final_model_used") or result.get("model") or ""),
                tokens_in=int(result.get("prompt_tokens") or 0),
                tokens_out=int(result.get("completion_tokens") or 0),
                cost_usd=float(result.get("cost_usd") or 0.0),
                status=str(result.get("execution_decision") or ""),
                latency_ms=float(latency_ms or 0.0),
                request_id=str(context.get("request_id") or ""),
                error_code=str(error_code or ""),
            )
        except Exception:
            pass

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

    @classmethod
    async def list_cli_dependencies(cls) -> Dict[str, Any]:
        return await ProviderConnectorService.list_cli_dependencies()

    @classmethod
    async def install_cli_dependency(cls, dependency_id: str):
        return await ProviderConnectorService.install_cli_dependency(dependency_id)

    @classmethod
    def get_cli_dependency_install_job(cls, dependency_id: str, job_id: str):
        return ProviderConnectorService.get_cli_dependency_install_job(dependency_id, job_id)
