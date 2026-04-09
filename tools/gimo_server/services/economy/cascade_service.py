"""Cascade execution: retry with progressively better models."""
from typing import Any, Dict, Optional
import logging

from ...ops_models import CascadeConfig, CascadeResult, QualityRating
from ..providers.service import ProviderService
from ..quality_service import QualityService
from ..model_router_service import ModelRouterService
from ..model_inventory_service import ModelInventoryService
from .cost_service import CostService

logger = logging.getLogger("orchestrator.services.cascade")


class CascadeService:
    def __init__(self, provider_service: ProviderService, model_router: ModelRouterService):
        self.provider_service = provider_service
        self.model_router = model_router

    async def execute_with_cascade(
        self,
        prompt: str,
        context: Dict[str, Any],
        cascade_config: CascadeConfig,
        node_budget: Optional[Dict[str, Any]] = None,
        current_state: Optional[Dict[str, Any]] = None,
    ) -> CascadeResult:
        chain = []
        current_model = context.get("model")

        if not current_model:
            # Pick cheapest available model as starting point
            models = ModelInventoryService.get_available_models()
            if models:
                cheapest = min(models, key=lambda m: (m.quality_tier, m.cost_input + m.cost_output))
                current_model = cheapest.model_id
            else:
                current_model = "unknown"

        attempts = 0
        max_attempts = max(1, cascade_config.max_escalations + 1)
        final_output = None
        total_cost = 0.0
        total_in = 0
        total_out = 0
        success = False

        while attempts < max_attempts:
            attempts += 1
            logger.info("Cascade attempt %s/%s using model %s", attempts, max_attempts, current_model)
            context["model"] = current_model

            try:
                output = await self.provider_service.generate(prompt, context)
                step_cost = float(output.get("cost_usd", 0.0) or 0.0)
                step_in = int(output.get("prompt_tokens", 0) or 0)
                step_out = int(output.get("completion_tokens", 0) or 0)
                total_cost += step_cost
                total_in += step_in
                total_out += step_out

                text_output = str(output.get("content") or output.get("result") or "")
                quality: QualityRating = QualityService.analyze_output(
                    text_output,
                    task_type=context.get("task_type"),
                    expected_format=context.get("expected_format"),
                )

                chain.append({
                    "attempt": attempts, "model": current_model,
                    "quality_score": quality.score, "alerts": quality.alerts,
                    "input_tokens": step_in, "output_tokens": step_out,
                    "cost_usd": step_cost,
                    "success": quality.score >= cascade_config.quality_threshold,
                })

                final_output = output
                final_output["quality_rating"] = quality.model_dump()
                final_output["cascade_level"] = attempts - 1

                if quality.score >= cascade_config.quality_threshold:
                    logger.info("Quality threshold met (%s >= %s)", quality.score, cascade_config.quality_threshold)
                    success = True
                    break
                else:
                    logger.warning("Low quality (score %s < %s)", quality.score, cascade_config.quality_threshold)

            except Exception as e:
                logger.error("Cascade attempt %s failed: %s", attempts, e)
                chain.append({
                    "attempt": attempts, "model": current_model,
                    "quality_score": 0, "error": str(e), "success": False,
                })
                if final_output is None:
                    final_output = {"error": str(e), "success": False, "cascade_level": attempts - 1}

            if attempts < max_attempts:
                if node_budget:
                    max_cost = node_budget.get("max_cost_usd")
                    if max_cost and total_cost >= float(max_cost):
                        logger.warning("Cascade stopped: budget cost limit reached")
                        break
                    max_tokens = node_budget.get("max_tokens")
                    if max_tokens and (total_in + total_out) >= int(max_tokens):
                        logger.warning("Cascade stopped: budget token limit reached")
                        break

                next_model = self._get_next_model(current_model, cascade_config)
                if next_model == current_model:
                    logger.warning("No higher tier available for escalation")
                    break
                current_model = next_model
            else:
                logger.warning("Max cascade attempts reached")

        savings = 0.0
        if success and chain:
            last_in = chain[-1].get("input_tokens", 0)
            last_out = chain[-1].get("output_tokens", 0)
            # Use the most expensive available model as benchmark
            models = ModelInventoryService.get_available_models()
            if models:
                benchmark = max(models, key=lambda m: m.cost_input + m.cost_output)
                hypothetical = CostService.calculate_cost(benchmark.model_id, last_in, last_out)
            else:
                hypothetical = CostService.calculate_cost(
                    cascade_config.max_tier or "opus", last_in, last_out)
            savings = hypothetical - total_cost

        return CascadeResult(
            final_output=final_output, cascade_chain=chain,
            total_input_tokens=total_in, total_output_tokens=total_out,
            total_tokens=total_in + total_out,
            total_cost_usd=total_cost, savings=savings, success=success,
        )

    def _get_next_model(self, current_model: str, config: CascadeConfig) -> str:
        """Find next higher-tier model from inventory."""
        current_entry = ModelInventoryService.find_model(current_model)
        current_tier = current_entry.quality_tier if current_entry else 3

        # Determine max tier from config
        max_tier = 5
        if config.max_tier:
            from ..model_router_service import _legacy_to_numeric
            max_numeric = _legacy_to_numeric(config.max_tier)
            if max_numeric:
                max_tier = max_numeric

        # Find model one tier above current
        candidates = ModelInventoryService.get_models_for_tier(current_tier + 1, max_tier)
        if not candidates:
            return current_model

        # Prefer cheapest in next tier
        return min(candidates, key=lambda m: m.cost_input + m.cost_output).model_id
