from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class ProviderAdapter(ABC):
    """Provider adapter interface."""

    @abstractmethod
    async def generate(self, prompt: str, context: Dict[str, Any]) -> str:
        """Generate draft content for a prompt.

        Must return a string (the draft content).
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Best-effort health check."""
