from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Coroutine

from ..config import DATA_DIR
from ..ops_models import (
    BudgetForecast,
    CascadeConfig,
    CascadeResult,
    QualityRating,
    UserEconomyConfig,
    WorkflowNode,
)


logger = logging.getLogger("orchestrator.economy")

GEMINI_PRO_MODEL = "gemini-2.5-pro"

class EconomyService:
    """Consolidated service for model pricing, cost prediction, and cascade execution."""

    PRICING_REGISTRY: Dict[str, Dict[str, float]] = {}
    _PRICING_LOADED = False

    MODEL_MAPPING = {
        "turbo": "gpt-4-turbo",
        "gpt-4o": "gpt-4o",
        "mini": "gpt-4o-mini",
        "gpt-4o-mini": "gpt-4o-mini",
        "sonnet": "claude-3-5-sonnet-20241022",
        "haiku": "claude-3-5-haiku-20241022",
        "opus": "claude-3-opus-20240229",
        "deepseek": "deepseek-chat",
        "gemini-pro": GEMINI_PRO_MODEL,
        "pro": GEMINI_PRO_MODEL,
        "local": "local",
    }

    @classmethod
    def load_pricing(cls):
        if cls._PRICING_LOADED: return
        pricing_path = Path(DATA_DIR) / "model_pricing.json"
        try:
            if pricing_path.exists():
                cls.PRICING_REGISTRY = json.loads(pricing_path.read_text(encoding="utf-8"))
                cls._PRICING_LOADED = True
            else:
                cls.PRICING_REGISTRY = {"local": {"input": 0.0, "output": 0.0}}
        except Exception as e:
            logger.error("Failed to load pricing: %s", e)
            cls.PRICING_REGISTRY = {"local": {"input": 0.0, "output": 0.0}}

    @classmethod
    def get_pricing(cls, model_name: str) -> Dict[str, float]:
        cls.load_pricing()
        m = model_name.lower()
        if m in cls.PRICING_REGISTRY: return cls.PRICING_REGISTRY[m]
        for key, val in cls.MODEL_MAPPING.items():
            if key in m and val in cls.PRICING_REGISTRY:
                return cls.PRICING_REGISTRY[val]
        return cls.PRICING_REGISTRY.get("local", {"input": 0.0, "output": 0.0})

    @classmethod
    def calculate_cost(cls, model: str, input_tokens: int, output_tokens: int) -> float:
        pricing = cls.get_pricing(model)
        return round((input_tokens/1e6)*pricing["input"] + (output_tokens/1e6)*pricing["output"], 6)

    @classmethod
    def calculate_roi(cls, quality_score: float, cost_usd: float) -> float:
        return float(quality_score) / (float(cost_usd) + 1e-6)

    # --- Prediction & Forecasting ---

    @staticmethod
    def predict_run_cost(nodes: List[WorkflowNode], _config: UserEconomyConfig) -> Dict[str, Any]:
        """Estimate total cost for a set of nodes."""
        total = 0.0
        breakdown = {}
        for node in nodes:
            if node.type != "llm_call": continue
            model = node.config.get("model") or "local"
            cost = EconomyService.calculate_cost(model, 1000, 500)
            total += cost
            breakdown[model] = breakdown.get(model, 0.0) + cost
        return {
            "estimated_cost": round(total, 4),
            "model_breakdown": breakdown
        }

    @staticmethod
    def forecast_budgets(_config: UserEconomyConfig) -> List[BudgetForecast]:
        """Place holder for budget forecasting logic."""
        return []

    # --- Cascade Logic ---

    @staticmethod
    async def execute_cascade(
        generator_fn: Callable[[str, Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]],
        analyzer_fn: Callable[[str, Optional[str]], QualityRating],
        prompt: str,
        context: Dict[str, Any],
        config: CascadeConfig
    ) -> CascadeResult:
        """Executes a prompt with automatic escalation to higher-tier models on quality failure."""
        chain = []
        current_model = context.get("model") or "local"
        attempts = 0
        total_cost = 0.0
        success = False
        final_output = None

        while attempts <= config.max_escalations:
            attempts += 1
            context["model"] = current_model
            try:
                output = await generator_fn(prompt, context)
                step_cost = float(output.get("cost_usd", 0.0))
                total_cost += step_cost
                
                text = str(output.get("content") or "")
                quality = analyzer_fn(text, context.get("task_type"))
                
                chain.append({
                    "attempt": attempts, "model": current_model,
                    "quality_score": quality.score, "cost_usd": step_cost,
                    "success": quality.score >= config.quality_threshold
                })
                final_output = output.copy()
                if quality.score >= config.quality_threshold:
                    success = True; break
                
                # Escalation logic
                if current_model == "local": current_model = "sonnet"
                elif "sonnet" in current_model: current_model = "opus"
                else: break

            except Exception as e:
                logger.error("Cascade attempt %s failed: %s", attempts, e)
                break

        return CascadeResult(
            final_output=final_output,
            cascade_chain=chain,
            total_cost_usd=total_cost,
            success=success
        )
