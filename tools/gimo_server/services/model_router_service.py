"""Provider-agnostic model router with hardware awareness."""
from __future__ import annotations

import logging
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from .storage_service import StorageService

from ..ops_models import WorkflowNode
from .cost_service import CostService
from .model_inventory_service import ModelInventoryService, ModelEntry
from .hardware_monitor_service import HardwareMonitorService

logger = logging.getLogger("orchestrator.model_router")


# Task-type → required capability + minimum quality tier
TASK_REQUIREMENTS: Dict[str, Tuple[str, int]] = {
    "classification": ("chat", 1),
    "code_generation": ("code", 3),
    "security_review": ("reasoning", 4),
    "formatting": ("chat", 1),
    "summarization": ("chat", 2),
    "translation": ("chat", 2),
    "analysis": ("chat", 3),
    "default": ("chat", 2),
}

# Legacy tier names → numeric tier (backwards compat)
_LEGACY_TIER_MAP = {"local": 1, "haiku": 2, "sonnet": 3, "opus": 5}
_LEGACY_TIERS = ["local", "haiku", "sonnet", "opus"]


def _legacy_to_numeric(tier: Optional[str]) -> Optional[int]:
    if tier is None:
        return None
    if isinstance(tier, int) or (isinstance(tier, str) and tier.isdigit()):
        return int(tier)
    return _LEGACY_TIER_MAP.get(str(tier).lower())


@dataclass
class RoutingDecision:
    model: str
    provider_id: str
    reason: str
    tier: int = 3
    alternatives: List[str] = field(default_factory=list)
    hardware_state: str = "safe"


@dataclass
class Phase6StrategyDecision:
    strategy_decision_id: str
    strategy_reason: str
    model_attempted: str
    failure_reason: str
    final_model_used: str
    fallback_used: bool
    final_status: str


class ModelRouterService:
    """Agnostic model router that uses only the user's configured providers."""

    @classmethod
    def resolve_tier_routing(cls, task_type: str, config: Any) -> Tuple[Optional[str], Optional[str]]:
        """Phase C: Returns (provider_id, model_id) based on configuration and task_type."""
        orchestrator_tasks = {"contract", "review", "orchestrator", "intent_classification", "classification", "analysis", "security_review", "disruptive_planning"}
        worker_tasks = {"coding", "code_generation", "test", "worker", "formatting", "doc_generation"}
        
        effective_provider = None
        requested_model = None
        
        roles = getattr(config, "roles", None)
        providers = getattr(config, "providers", None) or {}
        orchestrator_binding = config.primary_orchestrator_binding() if hasattr(config, "primary_orchestrator_binding") else None
        worker_binding = config.primary_worker_binding() if hasattr(config, "primary_worker_binding") else None

        if task_type in orchestrator_tasks:
            if orchestrator_binding:
                orch = orchestrator_binding
                if orch.provider_id in providers:
                    effective_provider = orch.provider_id
                    requested_model = orch.model
            elif roles and getattr(roles, "orchestrator", None):
                orch = roles.orchestrator
                if orch.provider_id in providers:
                    effective_provider = orch.provider_id
                    requested_model = orch.model
            elif getattr(config, "orchestrator_provider", None) and config.orchestrator_provider in providers:
                effective_provider = config.orchestrator_provider
                requested_model = getattr(config, "orchestrator_model", None)
        elif task_type in worker_tasks:
            if worker_binding:
                first_worker = worker_binding
                if first_worker.provider_id in providers:
                    effective_provider = first_worker.provider_id
                    requested_model = first_worker.model
            elif roles and getattr(roles, "workers", None):
                first_worker = next((w for w in roles.workers if w.provider_id in providers), None)
                if first_worker:
                    effective_provider = first_worker.provider_id
                    requested_model = first_worker.model
            elif getattr(config, "worker_provider", None) and config.worker_provider in providers:
                effective_provider = config.worker_provider
                requested_model = getattr(config, "worker_model", None)
                
        return effective_provider, requested_model

    # Keep for backwards compat with CascadeService and tests
    _TIERS = _LEGACY_TIERS

    DEFAULT_POLICY: Dict[str, str] = {
        "classification": "haiku",
        "code_generation": "sonnet",
        "security_review": "opus",
        "formatting": "local",
        "default": "sonnet",
    }

    PHASE6_PRIMARY_MODEL = "qwen3-coder:480b-cloud"
    PHASE6_FALLBACK_MODEL = "qwen3:8b"
    _PHASE6_FALLBACK_ALLOWED = {
        "429",
        "session_limit",
        "weekly_limit",
        "timeout",
        "network_error",
        "5xx",
        "provider_auth_expired",
        "provider_auth_refresh_failed",
    }
    _PHASE6_FALLBACK_FORBIDDEN = {
        "400",
        "policy_error",
        "schema_error",
        "merge_gate_error",
    }

    def __init__(self, storage: Optional["StorageService"] = None,
                 confidence_service: Optional[Any] = None):
        self.storage = storage
        self.confidence_service = confidence_service

    def _handle_explicit_model(self, explicit: str, hw_state: str, config: Any, reason_parts: list[str]) -> Optional[RoutingDecision]:
        entry = ModelInventoryService.find_model(str(explicit))
        if entry:
            if entry.is_local and hw_state == "critical":
                allow_override = getattr(config.economy, "allow_local_override", False) if hasattr(config, "economy") else False
                if not allow_override:
                    reason_parts.append(f"explicit:{explicit}->hw_critical_blocked")
                else:
                    return RoutingDecision(
                        model=entry.model_id, provider_id=entry.provider_id,
                        reason=f"explicit:{explicit}|hw_override",
                        tier=entry.quality_tier, hardware_state=hw_state,
                    )
            else:
                return RoutingDecision(
                    model=entry.model_id, provider_id=entry.provider_id,
                    reason=f"explicit:{explicit}",
                    tier=entry.quality_tier, hardware_state=hw_state,
                )
        return None

    def _adjust_tier_min_for_eco_mode(self, config: Any, tier_min: int, reason_parts: list[str]) -> int:
        if hasattr(config, "economy") and config.economy is not None and config.economy.eco_mode.mode != "off":
            eco = config.economy.eco_mode
            autonomy = config.economy.autonomy_level
            if autonomy in ("guided", "autonomous") and eco.mode == "binary":
                floor_tier = _legacy_to_numeric(eco.floor_tier) or 1
                tier_min = min(tier_min, floor_tier)
                reason_parts.append(f"eco:binary->tier_min={tier_min}")
        return tier_min

    def _adjust_tier_bounds(self, config: Any, tier_min: int, tier_max: int) -> Tuple[int, int]:
        if hasattr(config, "economy") and config.economy is not None:
            floor_val = _legacy_to_numeric(config.economy.model_floor)
            ceil_val = _legacy_to_numeric(config.economy.model_ceiling)
            if floor_val:
                tier_min = max(tier_min, floor_val)
            if ceil_val:
                tier_max = min(tier_max, ceil_val)
        return tier_min, tier_max

    def _filter_capabilities(self, all_models: list[ModelEntry], cap_needed: str, tier_min: int, tier_max: int, reason_parts: list[str]) -> list[ModelEntry]:
        candidates = [m for m in all_models
                      if cap_needed in m.capabilities
                      and tier_min <= m.quality_tier <= tier_max]

        if not candidates and cap_needed != "chat":
            candidates = [m for m in all_models
                          if "chat" in m.capabilities
                          and tier_min <= m.quality_tier <= tier_max]
            reason_parts.append(f"cap_relaxed:{cap_needed}->chat")
        return candidates

    def _is_caution_safe(self, m: ModelEntry) -> bool:
        if not m.is_local: 
            return True
        if m.size_gb is not None and m.size_gb <= 4.0: 
            return True
        if m.quality_tier <= 2: 
            return True
        return False

    def _filter_hardware(self, candidates: list[ModelEntry], hw_state: str, config: Any, reason_parts: list[str]) -> list[ModelEntry]:
        if hw_state == "critical":
            allow_override = getattr(config.economy, "allow_local_override", False) if hasattr(config, "economy") else False
            if not allow_override:
                remote_only = [m for m in candidates if not m.is_local]
                if remote_only:
                    candidates = remote_only
                    reason_parts.append("hw_critical:remote_only")
        elif hw_state == "caution":
            filtered = [m for m in candidates if self._is_caution_safe(m)]
            if filtered:
                candidates = filtered
                reason_parts.append("hw_caution:small_local_only")
        return candidates

    def _filter_gics_anomalies(self, candidates: list[ModelEntry], reason_parts: list[str]) -> list[ModelEntry]:
        """Exclude models flagged as anomalous by GICS (failure_streak >= 3).

        Fails open: if GICS is unavailable or raises, returns candidates unchanged.
        Never returns an empty list — always preserves at least the original set.
        """
        try:
            from .ops_service import OpsService
            gics = getattr(OpsService, "_gics", None)
            if not gics:
                return candidates
            filtered = []
            for m in candidates:
                try:
                    rel = gics.get_model_reliability(
                        provider_type=m.provider_id, model_id=m.model_id
                    )
                    if rel and rel.get("anomaly", False):
                        reason_parts.append(f"gics_anomaly_excluded:{m.model_id}")
                        continue
                except Exception:
                    pass
                filtered.append(m)
            return filtered if filtered else candidates
        except Exception:
            return candidates

    def _apply_eco_mode_selection(self, candidates: list[ModelEntry], config: Any, reason_parts: list[str], hw_state: str) -> Optional[RoutingDecision]:
        if hasattr(config, "economy") and config.economy is not None and config.economy.eco_mode.mode != "off":
            autonomy = config.economy.autonomy_level
            if autonomy in ("guided", "autonomous"):
                selected = min(candidates, key=lambda m: m.cost_input + m.cost_output)
                reason_parts.append(f"eco_select:{selected.model_id}")
                alts = [m.model_id for m in candidates if m.model_id != selected.model_id][:3]
                return RoutingDecision(
                    model=selected.model_id, provider_id=selected.provider_id,
                    reason="|".join(reason_parts), tier=selected.quality_tier,
                    alternatives=alts, hardware_state=hw_state,
                )
        return None

    async def _ensure_inventory_loaded(self) -> None:
        import time as _time
        if not ModelInventoryService._cache or (_time.time() - ModelInventoryService._cache_ts) > 300:
            try:
                await ModelInventoryService.refresh_inventory()
            except Exception:
                pass  # Fall back to minimal sync inventory

    async def choose_model(self, node: WorkflowNode, _state: Dict[str, Any]) -> RoutingDecision:
        from .ops_service import OpsService
        config = OpsService.get_config()

        await self._ensure_inventory_loaded()

        cfg = node.config if isinstance(node.config, dict) else {}
        task_type = str(cfg.get("task_type") or "").strip()
        reason_parts: list[str] = []

        hw = HardwareMonitorService.get_instance()
        hw_state = hw.get_load_level()

        explicit = cfg.get("model") or cfg.get("preferred_model")
        if explicit:
            decision = self._handle_explicit_model(str(explicit), hw_state, config, reason_parts)
            if decision:
                return decision

        cap_needed, tier_min = TASK_REQUIREMENTS.get(task_type, TASK_REQUIREMENTS["default"])
        reason_parts.append(f"task:{task_type or 'default'}(cap={cap_needed},tier>={tier_min})")

        tier_min = self._adjust_tier_min_for_eco_mode(config, tier_min, reason_parts)
        tier_max = 5
        tier_min, tier_max = self._adjust_tier_bounds(config, tier_min, tier_max)

        all_models = ModelInventoryService.get_available_models()
        if not all_models:
            return self._fallback_decision(reason_parts, hw_state)

        candidates = self._filter_capabilities(all_models, cap_needed, tier_min, tier_max, reason_parts)
        candidates = self._filter_hardware(candidates, hw_state, config, reason_parts)
        candidates = self._filter_gics_anomalies(candidates, reason_parts)

        if not candidates:
            candidates = [m for m in all_models if tier_min <= m.quality_tier <= tier_max]
            reason_parts.append("no_match:tier_only")

        if not candidates:
            return self._fallback_decision(reason_parts, hw_state)

        candidates = self._filter_budget_exhausted(candidates, config)
        if not candidates:
            return self._fallback_decision(reason_parts + ["all_budgets_exhausted"], hw_state)

        roi_pick = self._apply_roi_preference(candidates, task_type, config)
        if roi_pick:
            candidates = [roi_pick] + [m for m in candidates if m.model_id != roi_pick.model_id]
            reason_parts.append(f"roi:{roi_pick.model_id}")

        decision = self._apply_eco_mode_selection(candidates, config, reason_parts, hw_state)
        if decision:
            return decision

        selected = max(candidates, key=lambda m: m.quality_tier)
        alts = [m.model_id for m in candidates if m.model_id != selected.model_id][:3]
        reason_parts.append(f"selected:{selected.model_id}")

        return RoutingDecision(
            model=selected.model_id, provider_id=selected.provider_id,
            reason="|".join(reason_parts), tier=selected.quality_tier,
            alternatives=alts, hardware_state=hw_state,
        )

    def _fallback_decision(self, reason_parts: list, hw_state: str) -> RoutingDecision:
        """Fallback when no inventory models found — use active provider's model."""
        from .provider_service import ProviderService
        cfg = ProviderService.get_config()
        if cfg and cfg.active and cfg.active in cfg.providers:
            entry = cfg.providers[cfg.active]
            model = entry.model or entry.model_id or "unknown"
            reason_parts.append(f"fallback:{model}")
            return RoutingDecision(
                model=model, provider_id=cfg.active,
                reason="|".join(reason_parts), tier=3,
                hardware_state=hw_state,
            )
        reason_parts.append("no_provider")
        return RoutingDecision(
            model="unknown", provider_id="none",
            reason="|".join(reason_parts), tier=1,
            hardware_state=hw_state,
        )

    def _filter_budget_exhausted(self, candidates: list[ModelEntry], config: Any) -> list[ModelEntry]:
        if not self.storage or not hasattr(self.storage, "cost"):
            return candidates
        if not hasattr(config, "economy") or config.economy is None or not config.economy.provider_budgets:
            return candidates

        result = []
        for m in candidates:
            provider = m.provider_id
            if not self._is_provider_budget_exhausted(provider, config):
                result.append(m)
        return result if result else candidates  # Don't block all

    def _apply_roi_preference(self, candidates: list[ModelEntry], task_type: str, config: Any) -> Optional[ModelEntry]:
        if not self.storage or not hasattr(self.storage, "cost") or not task_type:
            return None
        if not (hasattr(config, "economy") and config.economy is not None and config.economy.allow_roi_routing):
            return None

        leaderboard = self.storage.cost.get_roi_leaderboard(days=30)
        candidate_ids = {m.model_id for m in candidates}

        for row in leaderboard:
            if row["task_type"] == task_type and row["sample_count"] >= 10:
                model_id = row["model"]
                if model_id in candidate_ids:
                    return next(m for m in candidates if m.model_id == model_id)
        return None

    def _is_provider_budget_exhausted(self, provider: str, config: Any) -> bool:
        if not self.storage or not hasattr(self.storage, "cost"):
            return False
        if not hasattr(config, "economy") or config.economy is None or not config.economy.provider_budgets:
            return False
        budget_cfg = next((b for b in config.economy.provider_budgets if b.provider == provider), None)
        if not budget_cfg or budget_cfg.max_cost_usd is None:
            return False
        period_days = {"daily": 1, "weekly": 7, "total": 3650}.get(budget_cfg.period, 30)
        spent = self.storage.cost.get_provider_spend(provider, days=period_days)
        return spent >= budget_cfg.max_cost_usd

    @classmethod
    def _classify_httpx_error(cls, exc: Exception) -> Optional[str]:
        import httpx
        if isinstance(exc, httpx.TimeoutException):
            return "timeout"
        if isinstance(exc, httpx.NetworkError):
            return "network_error"
        if getattr(exc, "response", None) is not None:
            try:
                code = int(exc.response.status_code)
                if code in (429, 400):
                    return str(code)
                if 500 <= code <= 599:
                    return "5xx"
            except Exception:
                pass
        return None

    @classmethod
    def classify_phase6_failure_reason(cls, exc: Exception) -> str:
        httpx_err = cls._classify_httpx_error(exc)
        if httpx_err:
            return httpx_err

        msg = str(exc or "").lower()
        if "limit" in msg:
            if "session" in msg: return "session_limit"
            if "weekly" in msg: return "weekly_limit"
            
        if any(k in msg for k in ("token expired", "auth expired", "provider_auth_expired")):
            return "provider_auth_expired"
            
        if "refresh" in msg and "failed" in msg:
            return "provider_auth_refresh_failed"
            
        if "merge gate" in msg or "merge_gate" in msg:
            return "merge_gate_error"
            
        if "schema" in msg: return "schema_error"
        if "policy" in msg: return "policy_error"
        
        return "unknown"

    @classmethod
    def resolve_phase6_strategy(
        cls,
        *,
        intent_effective: str,
        path_scope: List[str],
        primary_failure_reason: str = "",
    ) -> Phase6StrategyDecision:
        normalized_scope = [str(p or "").replace("\\", "/").lower() for p in (path_scope or [])]
        sensitive_scope = any(
            (
                "security" in p
                or "runtime_policy" in p
                or "baseline_manifest" in p
                or "policy.json" in p
                or "tools/gimo_server/mcp_bridge" in p
            )
            for p in normalized_scope
        )

        forced_local = intent_effective in {"SECURITY_CHANGE", "CORE_RUNTIME_CHANGE"} or sensitive_scope
        reason = str(primary_failure_reason or "")

        if forced_local:
            seed = f"forced_local|{intent_effective}|{','.join(normalized_scope)}"
            return Phase6StrategyDecision(
                strategy_decision_id=hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:16],
                strategy_reason="forced_local_only",
                model_attempted=cls.PHASE6_FALLBACK_MODEL,
                failure_reason="",
                final_model_used=cls.PHASE6_FALLBACK_MODEL,
                fallback_used=False,
                final_status="PRIMARY_MODEL_SUCCESS",
            )

        if not reason:
            seed = f"primary_success|{intent_effective}|{','.join(normalized_scope)}"
            return Phase6StrategyDecision(
                strategy_decision_id=hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:16],
                strategy_reason="cloud_primary_selected",
                model_attempted=cls.PHASE6_PRIMARY_MODEL,
                failure_reason="",
                final_model_used=cls.PHASE6_PRIMARY_MODEL,
                fallback_used=False,
                final_status="PRIMARY_MODEL_SUCCESS",
            )

        if reason in cls._PHASE6_FALLBACK_FORBIDDEN:
            seed = f"no_fallback|{reason}|{intent_effective}|{','.join(normalized_scope)}"
            return Phase6StrategyDecision(
                strategy_decision_id=hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:16],
                strategy_reason="fallback_forbidden",
                model_attempted=cls.PHASE6_PRIMARY_MODEL,
                failure_reason=reason,
                final_model_used=cls.PHASE6_PRIMARY_MODEL,
                fallback_used=False,
                final_status="PRIMARY_MODEL_SUCCESS",
            )

        if reason in cls._PHASE6_FALLBACK_ALLOWED:
            seed = f"fallback_allowed|{reason}|{intent_effective}|{','.join(normalized_scope)}"
            return Phase6StrategyDecision(
                strategy_decision_id=hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:16],
                strategy_reason="cloud_to_local_fallback",
                model_attempted=cls.PHASE6_PRIMARY_MODEL,
                failure_reason=reason,
                final_model_used=cls.PHASE6_FALLBACK_MODEL,
                fallback_used=True,
                final_status="FALLBACK_MODEL_USED",
            )

        seed = f"unknown_no_fallback|{reason}|{intent_effective}|{','.join(normalized_scope)}"
        return Phase6StrategyDecision(
            strategy_decision_id=hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:16],
            strategy_reason="fallback_not_allowed_unknown_reason",
            model_attempted=cls.PHASE6_PRIMARY_MODEL,
            failure_reason=reason,
            final_model_used=cls.PHASE6_PRIMARY_MODEL,
            fallback_used=False,
            final_status="PRIMARY_MODEL_SUCCESS",
        )

    # === Backwards-compatible methods ===

    def promote_eco_mode(self, node: WorkflowNode) -> Dict[str, Any]:
        """Best vs Eco recommendations for UI."""
        cfg = node.config if isinstance(node.config, dict) else {}
        task_type = str(cfg.get("task_type") or "").strip()
        cap_needed, tier_min = TASK_REQUIREMENTS.get(task_type, TASK_REQUIREMENTS["default"])

        all_models = ModelInventoryService.get_available_models()
        cap_models = [m for m in all_models if cap_needed in m.capabilities and m.quality_tier >= tier_min]
        if not cap_models:
            cap_models = [m for m in all_models if "chat" in m.capabilities]

        if not cap_models:
            return {"recommendations": {"best": {"model": "unknown", "reason": "no_models"}}, "saving_prospect": 0}

        best = max(cap_models, key=lambda m: m.quality_tier)
        eco = min(cap_models, key=lambda m: m.cost_input + m.cost_output)

        if best.model_id == eco.model_id:
            return {
                "recommendations": {"best": {"model": best.model_id, "reason": "only_option"}},
                "saving_prospect": 0,
            }

        impact = CostService.get_impact_comparison(best.model_id, eco.model_id)
        return {
            "recommendations": {
                "best": {"model": best.model_id, "reason": "highest_tier"},
                "eco": {"model": eco.model_id, "impact": impact},
            },
            "saving_prospect": impact["saving_pct"] if impact["status"] == "better" else 0,
        }

    async def check_provider_budget(self, node: WorkflowNode, _state: Dict[str, Any]) -> Optional[str]:
        try:
            await self.choose_model(node, _state)
            return None
        except ValueError as e:
            msg = str(e)
            if "budget exhausted" in msg.lower():
                return f"provider_budget_exhausted: {msg}"
            return None
        except Exception:
            return None
