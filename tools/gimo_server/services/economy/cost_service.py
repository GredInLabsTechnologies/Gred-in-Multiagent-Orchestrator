from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("orchestrator.services.cost")

class CostService:
    """Manages model pricing registry and cost calculations."""

    # Updated pricing (approximate USD per 1M tokens)
    PRICING_REGISTRY: Dict[str, Dict[str, float]] = {}
    
    _PRICING_LOADED = False

    @classmethod
    def load_pricing(cls):
        """Loads pricing from external JSON if not already loaded."""
        if cls._PRICING_LOADED:
            return
        
        import os
        import json
        from ...config import DATA_DIR
        
        pricing_path = os.path.join(DATA_DIR, "model_pricing.json")
        try:
            if os.path.exists(pricing_path):
                with open(pricing_path, "r") as f:
                    cls.PRICING_REGISTRY = json.load(f)
                    cls._PRICING_LOADED = True
            else:
                logger.warning(f"Pricing file not found at {pricing_path}, using defaults.")
                cls.PRICING_REGISTRY = {"local": {"input": 0.0, "output": 0.0}}
        except Exception as e:
            logger.error(f"Failed to load pricing database: {e}")
            cls.PRICING_REGISTRY = {"local": {"input": 0.0, "output": 0.0}}
    
    # Extended mapping for common aliases to canonical keys in pricing registry
    MODEL_MAPPING = {
        # Claude 4.x
        "opus-4": "claude-opus-4",
        "claude-opus-4": "claude-opus-4",
        "sonnet-4.5": "claude-sonnet-4-5",
        "claude-sonnet-4-5": "claude-sonnet-4-5",
        "haiku-4.5": "claude-haiku-4-5",
        "claude-haiku-4-5": "claude-haiku-4-5",
        # Claude 3.x (legacy)
        "sonnet": "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet": "claude-3-5-sonnet-20241022",
        "haiku": "claude-3-5-haiku-20241022",
        "claude-3-5-haiku": "claude-3-5-haiku-20241022",
        "opus": "claude-3-opus-20240229",
        "claude-3-opus": "claude-3-opus-20240229",
        # GPT-4.1
        "gpt-4.1": "gpt-4.1",
        "gpt-4.1-mini": "gpt-4.1-mini",
        "gpt-4.1-nano": "gpt-4.1-nano",
        # GPT-4o
        "gpt-4o": "gpt-4o",
        "gpt4o": "gpt-4o",
        "mini": "gpt-4o-mini",
        "gpt-4o-mini": "gpt-4o-mini",
        "turbo": "gpt-4-turbo",
        "gpt-4-turbo": "gpt-4-turbo",
        # Gemini
        "gemini-2.5-pro": "gemini-2.5-pro",
        "gemini-2.0-flash": "gemini-2.0-flash",
        "flash": "gemini-2.0-flash",
        "gemini-flash": "gemini-2.0-flash",
        "pro": "gemini-2.5-pro",
        "gemini-pro": "gemini-2.5-pro",
        "gemini-1.5-pro": "gemini-1.5-pro",
        "gemini-1.5-flash": "gemini-1.5-flash",
        # DeepSeek
        "deepseek-v3": "deepseek-v3",
        "deepseek": "deepseek-chat",
        "deepseek-chat": "deepseek-chat",
        "coder": "deepseek-coder",
        "deepseek-coder": "deepseek-coder",
        # Others
        "qwen": "qwen-2.5-72b",
        "qwen-2.5": "qwen-2.5-72b",
        "llama3": "meta-llama-3-70b",
        "llama-3": "meta-llama-3-70b",
        "llama-3-70b": "meta-llama-3-70b",
        "local": "local",
    }

    @classmethod
    def get_provider(cls, model_name: str) -> str:
        """Infers provider from model name."""
        m = str(model_name).lower()
        
        # Check mapping for aliases — prefer exact match, then substring
        canonical = m
        if m in cls.MODEL_MAPPING:
            canonical = cls.MODEL_MAPPING[m].lower()
        else:
            for key, value in cls.MODEL_MAPPING.items():
                if key in m:
                    canonical = value.lower()
                    break
        
        # Provider inference logic
        if "claude" in canonical or "anthropic" in canonical:
            return "anthropic"
        if "gpt" in canonical or "openai" in canonical:
             return "openai"
        if "gemini" in canonical or "google" in canonical:
            return "google"
        if "deepseek" in canonical:
            return "deepseek"
        if "meta" in canonical or "llama" in canonical:
            return "meta"
        if "qwen" in canonical:
            return "qwen"
        if "local" in canonical or "mistral" in canonical:
            return "local"
        
        return "unknown"

    @classmethod
    def get_pricing(cls, model_name: str) -> Dict[str, float]:
        """Returns input/output pricing per 1M tokens."""
        cls.load_pricing()
        m_name = str(model_name).lower()
        
        # Try direct match
        if m_name in cls.PRICING_REGISTRY:
            return cls.PRICING_REGISTRY[m_name]
        
        # Try mapping
        for key, value in cls.MODEL_MAPPING.items():
            if key in m_name:
                mapped_key = value
                if mapped_key in cls.PRICING_REGISTRY:
                    return cls.PRICING_REGISTRY[mapped_key]
                
        return cls.PRICING_REGISTRY.get("local", {"input": 0.0, "output": 0.0})

    @classmethod
    def calculate_cost(cls, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculates total cost in USD."""
        pricing = cls.get_pricing(model)
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return round(input_cost + output_cost, 6)

    @classmethod
    def get_impact_comparison(cls, model_a: str, model_b: str) -> Dict[str, Any]:
        """Compares two models and returns % impact (savings)."""
        p_a = cls.get_pricing(model_a)
        p_b = cls.get_pricing(model_b)
        
        avg_a = (p_a["input"] + p_a["output"]) / 2
        avg_b = (p_b["input"] + p_b["output"]) / 2
        
        if avg_a == 0:
            return {"saving_pct": 0, "status": "neutral"}
            
        impact = ((avg_a - avg_b) / avg_a) * 100
        if impact > 0:
            status = "better"
        elif impact < 0:
            status = "worse"
        else:
            status = "equal"
            
        return {
            "saving_pct": round(impact, 2),
            "status": status
        }

    @staticmethod
    def calculate_roi(quality_score: float, cost_usd: float) -> float:
        """Calculates Return on Investment (ROI) score for a completion.
        
        Formula: quality_score / (cost_usd + epsilon)
        Higher score means better quality/cost ratio.
        """
        epsilon = 1e-6
        # quality_score is typically 0-100 or 0.0-1.0. We assume 0-100 for consistency with quality_service.
        return float(quality_score) / (float(cost_usd) + epsilon)
