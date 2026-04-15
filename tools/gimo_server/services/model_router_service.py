"""Provider-agnostic model router with hardware awareness."""
from __future__ import annotations

import logging
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from .storage_service import StorageService

from ..ops_models import ProviderRoleBinding, WorkflowNode
from ..utils.debug_mode import is_debug_mode
from .economy.cost_service import CostService
from .model_inventory_service import ModelInventoryService, ModelEntry, _infer_capabilities, _infer_tier
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
class ModelSelectionDecision:
    """Result of model selection routing."""
    model: str
    provider_id: str
    reason: str
    tier: int = 3
    alternatives: List[str] = field(default_factory=list)
    hardware_state: str = "safe"


# Backward compatibility alias (renamed from RoutingDecision in P6)
RoutingDecision = ModelSelectionDecision


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
    """Agnostic model router that uses only the user's configured providers.

    Debug mode: routing remains active but decisions are tagged with
    ``debug_mode=True`` for downstream consumers.  Activate via DEBUG=true.
    """

    @property
    def debug_mode(self) -> bool:
        return is_debug_mode()

    @classmethod
    def normalize_task_type(cls, task_type: Optional[str]) -> str:
        normalized = str(task_type or "").strip().lower()
        mapping = {
            "orchestrator": "analysis",
            "planning": "analysis",
            "research": "analysis",
            "review": "analysis",
            "analysis": "analysis",
            "security": "security_review",
            "security_review": "security_review",
            "human_gate": "classification",
            "approval": "classification",
            "classification": "classification",
            "execution": "code_generation",
            "implementation": "code_generation",
            "worker": "code_generation",
            "coding": "code_generation",
            "code_generation": "code_generation",
            "test": "code_generation",
            "formatting": "formatting",
            "summarization": "summarization",
            "translation": "translation",
        }
        if normalized in TASK_REQUIREMENTS:
            return normalized
        return mapping.get(normalized, "default")

    @classmethod
    def resolve_tier_routing(cls, task_type: str, config: Any) -> Tuple[Optional[str], Optional[str]]:
        """Phase C: Returns (provider_id, model_id) based on configuration and task_type."""
        canonical_task_type = cls.normalize_task_type(task_type)
        orchestrator_tasks = {"contract", "review", "orchestrator", "intent_classification", "classification", "analysis", "security_review", "disruptive_planning"}
        worker_tasks = {"coding", "code_generation", "test", "worker", "formatting", "doc_generation"}
        
        effective_provider = None
        requested_model = None
        
        roles = getattr(config, "roles", None)
        providers = getattr(config, "providers", None) or {}
        orchestrator_binding = config.primary_orchestrator_binding() if hasattr(config, "primary_orchestrator_binding") else None
        worker_binding = config.primary_worker_binding() if hasattr(config, "primary_worker_binding") else None

        if canonical_task_type in orchestrator_tasks:
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
        elif canonical_task_type in worker_tasks:
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

    @classmethod
    def _inventory_entry_for_binding(cls, binding: ProviderRoleBinding) -> ModelEntry:
        from .providers.service import ProviderService

        for entry in ModelInventoryService.get_available_models():
            if entry.provider_id == binding.provider_id and entry.model_id == binding.model:
                return entry

        cfg = ProviderService.get_config()
        provider_entry = cfg.providers.get(binding.provider_id) if cfg and cfg.providers else None
        provider_type = ProviderService.normalize_provider_type(
            provider_entry.provider_type if provider_entry else binding.provider_id
        )
        is_local = False
        if provider_entry is not None:
            capabilities = getattr(provider_entry, "capabilities", None) or {}
            is_local = not bool(capabilities.get("requires_remote_api", True))
        pricing = CostService.get_pricing(binding.model)
        return ModelEntry(
            model_id=binding.model,
            provider_id=binding.provider_id,
            provider_type=provider_type,
            is_local=is_local,
            quality_tier=_infer_tier(binding.model),
            capabilities=_infer_capabilities(binding.model),
            cost_input=pricing.get("input", 0.0),
            cost_output=pricing.get("output", 0.0),
        )

    @classmethod
    def _filter_binding_candidates_for_task(
        cls,
        *,
        task_type: str,
        candidates: list[tuple[ProviderRoleBinding, ModelEntry]],
    ) -> tuple[list[tuple[ProviderRoleBinding, ModelEntry]], list[str], str, int]:
        normalized_task_type = cls.normalize_task_type(task_type)
        cap_needed, tier_min = TASK_REQUIREMENTS.get(normalized_task_type, TASK_REQUIREMENTS["default"])

        fully_qualified = [
            (binding, entry)
            for binding, entry in candidates
            if cap_needed in entry.capabilities and entry.quality_tier >= tier_min
        ]
        if fully_qualified:
            return fully_qualified, [], cap_needed, tier_min

        capability_only = [
            (binding, entry)
            for binding, entry in candidates
            if cap_needed in entry.capabilities
        ]
        if capability_only:
            return capability_only, ["quality_floor_relaxed_no_candidate"], cap_needed, tier_min

        if cap_needed != "chat":
            chat_floor = [
                (binding, entry)
                for binding, entry in candidates
                if "chat" in entry.capabilities and entry.quality_tier >= tier_min
            ]
            if chat_floor:
                return chat_floor, [f"capability_relaxed:{cap_needed}->chat"], cap_needed, tier_min

            chat_only = [
                (binding, entry)
                for binding, entry in candidates
                if "chat" in entry.capabilities
            ]
            if chat_only:
                return chat_only, [f"capability_relaxed:{cap_needed}->chat", "quality_floor_relaxed_no_candidate"], cap_needed, tier_min

        return list(candidates), ["capability_and_quality_floor_unavailable"], cap_needed, tier_min

    @classmethod
    def _gics_success_adjustment(cls, task_type: str, entry: ModelEntry) -> tuple[float, list[str]]:
        from .capability_profile_service import CapabilityProfileService
        from .ops_service import OpsService

        reasons: list[str] = []
        adjustment = 0.0

        reliability = OpsService.get_model_reliability(provider_type=entry.provider_type, model_id=entry.model_id) or {}
        if reliability:
            score = max(0.0, min(1.0, float(reliability.get("score", 0.5) or 0.5)))
            adjustment += (score - 0.5) * 0.4
            reasons.append(f"gics_reliability={score:.2f}")
            if reliability.get("anomaly"):
                adjustment -= 0.25
                reasons.append("gics_anomaly_penalty=0.25")

        capability = CapabilityProfileService.get_capability(
            provider_type=entry.provider_type,
            model_id=entry.model_id,
            task_type=task_type,
        )
        if capability and capability.samples >= 2:
            capability_adjust = max(-0.2, min(0.2, (capability.success_rate - 0.5) * 0.4))
            adjustment += capability_adjust
            reasons.append(
                f"gics_task_success={capability.success_rate:.2f}/samples={capability.samples}"
            )

        return adjustment, reasons

    @classmethod
    def choose_binding_from_candidates(
        cls,
        *,
        task_type: str,
        candidates: list[ProviderRoleBinding],
        requested_provider: str | None = None,
        requested_model: str | None = None,
    ) -> ModelSelectionDecision:
        from .providers.service import ProviderService
        from .providers.topology_service import ProviderTopologyService

        constrained_candidates = ProviderTopologyService.constrain_bindings(
            list(candidates or []),
            requested_provider=requested_provider,
            requested_model=requested_model,
        )
        if not constrained_candidates:
            return ModelSelectionDecision(
                model="auto",
                provider_id="auto",
                reason="objective=constraints>success>quality>latency>cost|selected=auto/auto|no_candidates",
            )

        evaluated_candidates = [
            (binding, cls._inventory_entry_for_binding(binding))
            for binding in constrained_candidates
        ]
        ranked_candidates, eligibility_notes, cap_needed, tier_min = cls._filter_binding_candidates_for_task(
            task_type=task_type,
            candidates=evaluated_candidates,
        )
        normalized_task_type = cls.normalize_task_type(task_type)
        cfg = ProviderService.get_config()
        preferred_provider, preferred_model = (None, None)
        if cfg is not None:
            preferred_provider, preferred_model = cls.resolve_tier_routing(normalized_task_type, cfg)

        ranked: list[tuple[tuple[float, float, float, float, str, str], RoutingDecision]] = []
        for binding, entry in ranked_candidates:
            topology_bonus = 0.0
            if preferred_provider and binding.provider_id == preferred_provider:
                topology_bonus = 1.0 if not preferred_model or binding.model == preferred_model else 0.7
            gics_adjustment, gics_reasons = cls._gics_success_adjustment(normalized_task_type, entry)
            success_score = topology_bonus + gics_adjustment
            quality_score = (1.0 if entry.quality_tier >= tier_min else 0.0) + (entry.quality_tier / 100.0)
            latency_score = (1.0 if entry.is_local else 0.0) + (0.0 if not entry.size_gb else max(0.0, 0.5 - (entry.size_gb / 100.0)))
            total_cost = max(0.0, entry.cost_input) + max(0.0, entry.cost_output)
            cost_score = 1.0 if total_cost <= 0 else max(0.0, 1.0 - min(total_cost, 1000.0) / 1000.0)
            reason_parts = [
                "objective=constraints>success>quality>latency>cost",
                f"task={normalized_task_type}(cap={cap_needed},tier>={tier_min})",
                f"selected={binding.provider_id}/{binding.model}",
                f"success={success_score:.2f}",
                f"quality={quality_score:.2f}",
                f"latency={latency_score:.2f}",
                f"cost={cost_score:.2f}",
            ]
            if preferred_provider:
                reason_parts.append(f"topology_preference={preferred_provider}/{preferred_model or 'auto'}")
            reason_parts.extend(eligibility_notes)
            reason_parts.extend(gics_reasons)

            ranked.append(
                (
                    (
                        success_score,
                        quality_score,
                        latency_score,
                        cost_score,
                        binding.provider_id,
                        binding.model,
                    ),
                    RoutingDecision(
                        model=binding.model,
                        provider_id=binding.provider_id,
                        reason="|".join(reason_parts),
                        tier=entry.quality_tier,
                        hardware_state="safe",
                    ),
                )
            )

        ranked.sort(
            key=lambda item: (
                -item[0][0],
                -item[0][1],
                -item[0][2],
                -item[0][3],
                item[0][4],
                item[0][5],
            )
        )
        selected = ranked[0][1]
        selected.alternatives = [candidate.model for _, candidate in ranked[1:4]]
        return selected

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
                    return ModelSelectionDecision(
                        model=entry.model_id, provider_id=entry.provider_id,
                        reason=f"explicit:{explicit}|hw_override",
                        tier=entry.quality_tier, hardware_state=hw_state,
                    )
            else:
                return ModelSelectionDecision(
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
                return ModelSelectionDecision(
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

    async def choose_model(self, node: WorkflowNode, _state: Dict[str, Any]) -> ModelSelectionDecision:
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

        return ModelSelectionDecision(
            model=selected.model_id, provider_id=selected.provider_id,
            reason="|".join(reason_parts), tier=selected.quality_tier,
            alternatives=alts, hardware_state=hw_state,
        )

    def _fallback_decision(self, reason_parts: list, hw_state: str) -> ModelSelectionDecision:
        """Fallback when no inventory models found — use active provider's model."""
        from .providers.service import ProviderService
        cfg = ProviderService.get_config()
        if cfg and cfg.active and cfg.active in cfg.providers:
            entry = cfg.providers[cfg.active]
            model = entry.model or entry.model_id or "unknown"
            reason_parts.append(f"fallback:{model}")
            return ModelSelectionDecision(
                model=model, provider_id=cfg.active,
                reason="|".join(reason_parts), tier=3,
                hardware_state=hw_state,
            )
        reason_parts.append("no_provider")
        return ModelSelectionDecision(
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
