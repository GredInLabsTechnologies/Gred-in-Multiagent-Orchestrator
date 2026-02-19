from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from .storage_service import StorageService

from ..ops_models import WorkflowNode
from .cost_service import CostService


@dataclass
class RoutingDecision:
    model: str
    reason: str
    tier: Optional[str] = None


class ModelRouterService:
    """Simple model router MVP for phase 3.3.

    Chooses model by task_type and can degrade to cheaper tier when budget is tight.
    """

    DEFAULT_POLICY: Dict[str, str] = {
        "classification": "haiku",
        "code_generation": "sonnet",
        "security_review": "opus",
        "formatting": "local",
        "default": "sonnet",
    }

    _TIERS = ["local", "haiku", "sonnet", "opus"]

    def __init__(self, storage: Optional["StorageService"] = None, confidence_service: Optional["ConfidenceService"] = None):
        self.storage = storage
        self.confidence_service = confidence_service

    async def choose_model(self, node: WorkflowNode, state: Dict[str, Any]) -> RoutingDecision:
        from .ops_service import OpsService
        config = OpsService.get_config()

        cfg = node.config if isinstance(node.config, dict) else {}
        task_type = str(cfg.get("task_type") or "").strip()
        
        # Determine base model
        base_model = str(
            cfg.get("model")
            or cfg.get("preferred_model")
            or self.DEFAULT_POLICY.get(task_type, self.DEFAULT_POLICY["default"])
        )
        
        final_model = base_model
        reason = f"policy:{task_type or 'default'}"

        # 0. ROI Routing (Opt-in)
        final_model, reason = self._apply_roi_routing(final_model, reason, task_type, config)

        # 0.5. Eco-Mode Logic
        final_model, reason = await self._apply_eco_mode(final_model, reason, node, state, config)

        # 1. Provider Budget Constraint
        final_model, reason = self._apply_provider_budget(final_model, reason, config)

        # 2. Low Budget degradation
        final_model, reason = self._apply_low_budget_degradation(final_model, reason, state)

        # 3. User Bounds (Floor/Ceiling) - ABSOLUTE ENFORCEMENT
        final_model, reason = self._apply_user_bounds(final_model, reason, config)

        resolved_model, resolve_reason = self._resolve_provider_model(final_model, node, state, config)
        if resolve_reason:
            reason = f"{reason}|{resolve_reason}"

        return RoutingDecision(model=resolved_model, reason=reason, tier=final_model)

    def _resolve_provider_model(
        self,
        selected_tier_or_model: str,
        node: WorkflowNode,
        state: Dict[str, Any],
        config: Any,
    ) -> Tuple[str, str]:
        """Resolve logical tier (haiku/sonnet/opus/local) to physical model id.

        Sources (priority):
        1) node.config.provider_model_map
        2) state.provider_model_map
        3) config.economy.provider_model_map
        """
        tier = str(selected_tier_or_model)
        if tier not in self._TIERS:
            return tier, ""

        provider_type = self._resolve_active_provider_type(state)
        if not provider_type:
            return tier, ""

        cfg = node.config if isinstance(node.config, dict) else {}
        node_map = cfg.get("provider_model_map") if isinstance(cfg.get("provider_model_map"), dict) else {}
        state_map = state.get("provider_model_map") if isinstance(state.get("provider_model_map"), dict) else {}
        eco_map = {}
        if hasattr(config, "economy") and isinstance(getattr(config.economy, "provider_model_map", None), dict):
            eco_map = config.economy.provider_model_map

        combined: Dict[str, Any] = {}
        combined.update(eco_map)
        combined.update(state_map)
        combined.update(node_map)

        provider_entry = combined.get(provider_type)
        if not isinstance(provider_entry, dict):
            return tier, ""

        mapped = provider_entry.get(tier)
        if isinstance(mapped, str) and mapped.strip():
            return mapped.strip(), f"provider_map:{provider_type}:{tier}->{mapped.strip()}"

        return tier, ""

    def _resolve_active_provider_type(self, state: Dict[str, Any]) -> Optional[str]:
        from .provider_service import ProviderService

        st_provider = state.get("active_provider_type")
        if isinstance(st_provider, str) and st_provider.strip():
            return st_provider.strip()

        cfg = ProviderService.get_config()
        if not cfg:
            return None

        if cfg.provider_type:
            return str(cfg.provider_type)

        if cfg.active and cfg.active in cfg.providers:
            entry = cfg.providers[cfg.active]
            return str(entry.provider_type or entry.type)

        return None

    def _apply_roi_routing(self, current_model: str, current_reason: str, task_type: str, config: Any) -> Tuple[str, str]:
        autonomy = config.economy.autonomy_level if hasattr(config, "economy") else "manual"
        
        if hasattr(config, "economy") and config.economy.allow_roi_routing:
            roi_model = self._choose_model_with_roi(task_type, config)
            if roi_model and roi_model != current_model:
                if autonomy in ["guided", "autonomous"]:
                    return roi_model, f"roi_routing:{task_type}->{roi_model}"
                elif autonomy == "advisory":
                    return current_model, current_reason + f" (ROI recommendation: {roi_model})"
        return current_model, current_reason

    async def _apply_eco_mode(self, current_model: str, current_reason: str, node: WorkflowNode, state: Dict[str, Any], config: Any) -> Tuple[str, str]:
        autonomy = config.economy.autonomy_level if hasattr(config, "economy") else "manual"
        
        if not (hasattr(config, "economy") and autonomy in ["guided", "autonomous"] and config.economy.eco_mode.mode != "off"):
            return current_model, current_reason
        
        eco = config.economy.eco_mode
        
        if eco.mode == "binary":
            # If eco_model_candidate was already applied and is the floor, this is redundant.
            # If not, this ensures the floor is respected.
            if self._TIERS.index(eco.floor_tier) <= self._TIERS.index(current_model):
                return eco.floor_tier, f"eco_mode:binary->{eco.floor_tier}"
        
        elif eco.mode == "smart" and self.confidence_service:
            projection = await self._get_confidence_projection(node, state, cfg=node.config if isinstance(node.config, dict) else {})
            
            if projection:
                score = projection["score"]
                risk = projection.get("risk_level", "medium")
                
                if score >= eco.confidence_threshold_aggressive and risk == "low":
                    # High confidence, low risk -> jump to floor
                    return eco.floor_tier, f"eco_mode:smart(agg={score})->{eco.floor_tier}"
                elif score >= eco.confidence_threshold_moderate:
                    # Moderate confidence -> degrade one tier
                    degraded = self._degrade(current_model)
                    # Don't go below eco floor
                    if self._is_below_floor(degraded, eco.floor_tier):
                        degraded = eco.floor_tier
                    return degraded, f"eco_mode:smart(mod={score})->{degraded}"
        
        return current_model, current_reason

    def _apply_provider_budget(self, current_model: str, current_reason: str, config: Any) -> Tuple[str, str]:
        provider = CostService.get_provider(current_model)
        if self._is_provider_budget_exhausted(provider, config):
            # Try to degrade to different provider
            degraded = self._degrade(current_model)
            if CostService.get_provider(degraded) != provider and not self._is_provider_budget_exhausted(CostService.get_provider(degraded), config):
                return degraded, f"budget_exhausted:{provider}->{degraded}"
            else:
                # Fallback to local if not already local
                if provider != "local" and not self._is_provider_budget_exhausted("local", config):
                     return "local", f"budget_exhausted:{provider}->local"
                else:
                    # Error if no fallback
                    raise ValueError(f"Budget exhausted for provider '{provider}' and no suitable fallback found.")
        return current_model, current_reason

    def _apply_low_budget_degradation(self, current_model: str, current_reason: str, state: Dict[str, Any]) -> Tuple[str, str]:
        if self._is_low_budget(state):
            degraded = self._degrade(current_model)
            if degraded != current_model:
                 return degraded, f"low_budget:{current_reason}->{degraded}"
        return current_model, current_reason

    def _apply_user_bounds(self, current_model: str, current_reason: str, config: Any) -> Tuple[str, str]:
        if hasattr(config, "economy"):
            floor = config.economy.model_floor
            ceiling = config.economy.model_ceiling
            
            if floor and self._is_below_floor(current_model, floor):
                return floor, f"bounded:floor({floor})"
            if ceiling and self._is_above_ceiling(current_model, ceiling):
                 return ceiling, f"bounded:ceiling({ceiling})"
        return current_model, current_reason

    async def _get_confidence_projection(self, node: WorkflowNode, state: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Use proactive confidence projection
        projection = state.get("node_confidence", {}).get(node.id)
        if not projection:
            task_desc = cfg.get("description", cfg.get("task", ""))
            if task_desc:
                try:
                    projection = await self.confidence_service.project_confidence(task_desc, state)
                    # Store in state so GraphEngine's proactive check (and subsequent calls) can reuse it
                    state.setdefault("node_confidence", {})[node.id] = projection
                except Exception as e:
                    from .ops_service import logger as ops_logger
                    ops_logger.error("Confidence projection failed for node %s: %s", node.id, e)
                    projection = None # Fallback to base_model logic
        return projection

    def promote_eco_mode(self, node: WorkflowNode, state: Dict[str, Any]) -> Dict[str, Any]:
        """Provides Best vs Eco recommendations. Note: this stays sync for UI but uses current config."""
        from .ops_service import OpsService
        config = OpsService.get_config()
        
        cfg = node.config if isinstance(node.config, dict) else {}
        task_type = str(cfg.get("task_type") or "").strip()
        
        best_model = str(
            cfg.get("model")
            or cfg.get("preferred_model")
            or self.DEFAULT_POLICY.get(task_type, self.DEFAULT_POLICY["default"])
        )

        if not hasattr(config, "economy") or config.economy.eco_mode.mode == "off":
            return {
                "recommendations": {
                    "best": {"model": best_model, "reason": "user_preferred"}
                },
                "saving_prospect": 0
            }

        eco_model = self._degrade(best_model)
        
        # Respect floor if configured
        if hasattr(config, "economy") and config.economy.eco_mode.floor_tier:
            if self._is_below_floor(eco_model, config.economy.eco_mode.floor_tier):
                eco_model = config.economy.eco_mode.floor_tier

        impact = CostService.get_impact_comparison(best_model, eco_model)
        
        return {
            "recommendations": {
                "best": {"model": best_model, "reason": "user_preferred"},
                "eco": {"model": eco_model, "impact": impact}
            },
            "saving_prospect": impact["saving_pct"] if impact["status"] == "better" else 0
        }

    def _is_low_budget(self, state: Dict[str, Any]) -> bool:
        budget = state.get("budget") if isinstance(state.get("budget"), dict) else {}
        counters = state.get("budget_counters") if isinstance(state.get("budget_counters"), dict) else {}
        max_cost = budget.get("max_cost_usd")
        if not isinstance(max_cost, (int, float)) or float(max_cost) <= 0:
            return False
        spent = float(counters.get("cost_usd", 0.0) or 0.0)
        remaining_ratio = max(0.0, (float(max_cost) - spent) / float(max_cost))
        return remaining_ratio < 0.2

    def _degrade(self, model: str) -> str:
        m = str(model)
        if m not in self._TIERS:
            return m
        idx = self._TIERS.index(m)
        return self._TIERS[max(0, idx - 1)]

    def _is_below_floor(self, model: str, floor: str) -> bool:
        if model not in self._TIERS or floor not in self._TIERS:
            return False
        return self._TIERS.index(model) < self._TIERS.index(floor)

    def _is_above_ceiling(self, model: str, ceiling: str) -> bool:
        if model not in self._TIERS or ceiling not in self._TIERS:
            return False
        return self._TIERS.index(model) > self._TIERS.index(ceiling)

    async def _degrade_one_tier(self, model: str) -> str:
        # Placeholder for complex degradation logic if needed
        return self._degrade(model)

    def _choose_model_with_roi(self, task_type: str, config: Any) -> Optional[str]:
        """Internal helper to choose model based on ROI leaderboard."""
        if not self.storage or not hasattr(self.storage, "cost") or not task_type:
            return None
            
        leaderboard = self.storage.cost.get_roi_leaderboard(days=30)
        # Filter for this task_type and count >= 10
        candidates = [
            row for row in leaderboard 
            if row["task_type"] == task_type and row["sample_count"] >= 10
        ]
        
        if not candidates:
            return None
            
        # Top candidate (leaderboard is sorted by roi_score DESC)
        best = candidates[0]
        model = best["model"]
        
        # Verify model is available in tiers
        if model not in self._TIERS:
            return None
            
        # ROI routing should still respect bounds
        floor = config.economy.model_floor
        ceiling = config.economy.model_ceiling
        
        if floor and self._is_below_floor(model, floor):
             return None # Don't suggest if below floor
        if ceiling and self._is_above_ceiling(model, ceiling):
             return None # Don't suggest if above ceiling
             
        # Only return if it's actually different/better (implicitly handled by caller)
        return model

    def _is_provider_budget_exhausted(self, provider: str, config: Any) -> bool:
        if not self.storage or not hasattr(self.storage, "cost"):
            return False
        if not hasattr(config, "economy") or not config.economy.provider_budgets:
            return False
        budget_cfg = next((b for b in config.economy.provider_budgets if b.provider == provider), None)
        if not budget_cfg or budget_cfg.max_cost_usd is None:
            return False
        period_days = 30
        if budget_cfg.period == "daily": period_days = 1
        elif budget_cfg.period == "weekly": period_days = 7
        elif budget_cfg.period == "total": period_days = 3650
        spent = self.storage.cost.get_provider_spend(provider, days=period_days)
        return spent >= budget_cfg.max_cost_usd

    async def check_provider_budget(self, node: WorkflowNode, state: Dict[str, Any]) -> Optional[str]:
        """Checks if the node execution is blocked by provider budget.
        
        Returns error reason if blocked, None otherwise.
        """
        try:
            # Re-use the routing logic to see if a valid model can be selected
            # Note: This is an async call
            await self.choose_model(node, state)
            return None
        except ValueError as e:
            msg = str(e)
            if "budget exhausted" in msg.lower():
                return f"provider_budget_exhausted: {msg}"
            return None
        except Exception:
            # Allow other errors to bubble up during actual execution
            return None
