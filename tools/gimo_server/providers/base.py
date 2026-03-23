from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ProviderAdapter(ABC):
    """Provider adapter interface."""

    @abstractmethod
    async def generate(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate draft content for a prompt.

        Returns a dictionary with:
        - "content": str (the generated text)
        - "usage": dict (optional tokens usage info)
        """

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Call chat completions with tool_calls support.

        Args:
            messages: List of message dicts with "role" and "content"
            tools: Optional list of tool definitions in OpenAI format
            temperature: Sampling temperature
            max_tokens: Optional output-token budget for the response
            response_format: Optional provider-native response format payload

        Returns:
            {
                "content": str | None,
                "tool_calls": List[{"id": str, "function": {"name": str, "arguments": str}}],
                "usage": dict,
                "finish_reason": str,
            }
        """
        raise NotImplementedError("chat_with_tools not implemented for this adapter")

    @abstractmethod
    async def health_check(self) -> bool:
        """Best-effort health check."""
