from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...ops_models import WorkflowNode, UserEconomyConfig
from .cost_service import CostService
from ..storage_service import StorageService

logger = logging.getLogger("orchestrator.services.cost_predictor")

class CostPredictor:
    """Predicts workflow costs based on historical usage and static pricing."""

    def __init__(self, storage: Optional[StorageService] = None):
        self.storage = storage or StorageService()

    def predict_workflow_cost(
        self,
        nodes: List[WorkflowNode],
        state: Dict[str, Any],
        economy_config: UserEconomyConfig
    ) -> Dict[str, Any]:
        """Estimates the total cost for a list of nodes and an initial state.

        Args:
            nodes: The list of nodes to execute.
            state: The current state (used for dynamic dependencies, if any).
            economy_config: The user's economy settings.

        Returns:
            A dictionary with estimated_cost, confidence_interval, and model_breakdown.
        """
        total_estimated_cost = 0.0
        model_breakdown = {}
        samples_found = 0
        total_nodes = len(nodes)
        total_llm_nodes = 0

        # Build set of allowed providers from user config
        allowed_providers: Optional[set] = None
        if economy_config.provider_budgets:
            allowed_providers = {b.provider for b in economy_config.provider_budgets}

        for node in nodes:
            if node.type != "llm_call":
                continue

            total_llm_nodes += 1

            task_type = node.config.get("task_type", "generic")
            model = node.config.get("model")

            if not model:
                from ..providers.service import ProviderService
                provider_cfg = ProviderService.get_config()
                if provider_cfg and provider_cfg.active in provider_cfg.providers:
                    model = provider_cfg.providers[provider_cfg.active].model
                else:
                    model = "haiku"

            # Filter: skip models whose provider is not in user's configured providers
            if allowed_providers:
                model_provider = CostService.get_provider(model)
                if model_provider not in allowed_providers and model_provider != "local":
                    # Use fallback model from an allowed provider or local
                    model = "local"
            
            # 1. Try historical lookup by task_type AND model
            hist = self.storage.cost.get_avg_cost_by_task_type(task_type, model=model)
            
            if hist["sample_count"] >= 5:
                # Use historical average for this specific model/task combo
                estimated_node_cost = hist["avg_cost"]
                samples_found += 1
            else:
                # 2. Try historical lookup by task_type only (any model)
                hist_generic = self.storage.cost.get_avg_cost_by_task_type(task_type)
                if hist_generic["sample_count"] >= 5:
                    # Use generic average but maybe adjust it? 
                    # For now, we take it as is, but we could scale it by model price ratios.
                    estimated_node_cost = hist_generic["avg_cost"]
                    samples_found += 0.5 # Partial weight for non-exact match
                else:
                    # 3. Fallback to static pricing (assuming generic token counts)
                    input_tokens = 1000
                    output_tokens = 500
                    estimated_node_cost = CostService.calculate_cost(model, input_tokens, output_tokens)
            
            total_estimated_cost += estimated_node_cost
            
            # Track breakdown
            if model not in model_breakdown:
                model_breakdown[model] = 0.0
            model_breakdown[model] += estimated_node_cost

        # Calculate confidence score based on LLM nodes
        confidence_score = 0.0
        if total_llm_nodes > 0:
            confidence_score = samples_found / total_llm_nodes
        elif total_nodes > 0:
            # If no LLM nodes but there are other nodes, we are "confident" in the zero cost
            confidence_score = 1.0
            
        # Standard deviation heuristic if we have history
        low_bound = total_estimated_cost * 0.8
        high_bound = total_estimated_cost * 1.5
        
        return {
            "estimated_cost": round(total_estimated_cost, 4),
            "confidence_score": round(confidence_score, 2),
            "interval": {
                "low": round(low_bound, 4),
                "high": round(high_bound, 4)
            },
            "model_breakdown": {m: round(c, 4) for m, c in model_breakdown.items()},
            "samples_found": samples_found,
            "total_llm_nodes": total_llm_nodes
        }
