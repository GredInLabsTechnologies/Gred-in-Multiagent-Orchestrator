from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set

logger = logging.getLogger("orchestrator.providers.inventory")


@dataclass
class ModelEntry:
    model_id: str
    provider_id: str
    provider_type: str
    is_local: bool
    quality_tier: int
    capabilities: Set[str] = field(default_factory=lambda: {"chat"})
    cost_input: float = 0.0
    cost_output: float = 0.0


class ModelInventory:
    """Unified registry of available models across all configured providers."""

    _models: List[ModelEntry] = []

    @classmethod
    def update(cls, entries: List[ModelEntry]) -> None:
        cls._models = entries
        logger.info(f"Inventory updated with {len(entries)} models.")

    @classmethod
    def get_all(cls) -> List[ModelEntry]:
        return cls._models

    @classmethod
    def find(cls, model_id: str) -> Optional[ModelEntry]:
        for m in cls._models:
            if m.model_id == model_id:
                return m
        return None

    @classmethod
    def get_by_tier(cls, min_tier: int) -> List[ModelEntry]:
        return [m for m in cls._models if m.quality_tier >= min_tier]

    @staticmethod
    def infer_tier(model_id: str) -> int:
        mid = model_id.lower()
        if any(x in mid for x in ["opus", "gpt-4o", "ultra"]): return 5
        if any(x in mid for x in ["sonnet", "gpt-4", "pro"]): return 4
        if any(x in mid for x in ["haiku", "mini", "flash"]): return 3
        return 2
