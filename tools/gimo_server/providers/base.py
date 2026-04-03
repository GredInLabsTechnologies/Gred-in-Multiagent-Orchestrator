from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .tool_call_parser import parse_tool_calls_from_text


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

        Wraps _raw_chat_with_tools() with normalisation so the agentic loop
        always receives a uniform contract regardless of provider.

        Returns:
            {
                "content": str | None,
                "tool_calls": List[{"id": str, "function": {"name": str, "arguments": str}}],
                "usage": dict,
                "finish_reason": str,
            }
        """
        result = await self._raw_chat_with_tools(
            messages, tools=tools, temperature=temperature,
            max_tokens=max_tokens, response_format=response_format,
        )
        return self._normalise_tool_calls(result)

    async def _raw_chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Subclasses override this to implement provider-specific logic."""
        raise NotImplementedError("_raw_chat_with_tools not implemented for this adapter")

    @staticmethod
    def _normalise_tool_calls(result: Dict[str, Any]) -> Dict[str, Any]:
        """Guarantee: tool_calls is always a normalised list.

        If the provider returned tool_calls natively, tag as "native".
        If not, attempt to parse JSON-in-text from content and tag as
        "parsed_json_in_text". This format tag enables per-provider
        observability — no other framework tracks HOW tool calls arrived.
        """
        # If the adapter already set tool_call_format (e.g. CLI adapter with
        # retry logic), respect it — don't override with incorrect tag.
        if result.get("tool_call_format"):
            return result

        tool_calls = result.get("tool_calls") or []
        content = result.get("content") or ""
        if tool_calls:
            result["tool_call_format"] = "native"
        elif content:
            remaining, parsed = parse_tool_calls_from_text(content)
            if parsed:
                result["content"] = remaining
                result["tool_calls"] = parsed
                result["tool_call_format"] = "parsed_json_in_text"
                if result.get("finish_reason") == "stop":
                    result["finish_reason"] = "tool_calls"
            else:
                result["tool_call_format"] = "none"
        else:
            result["tool_call_format"] = "none"
        return result

    @abstractmethod
    async def health_check(self) -> bool:
        """Best-effort health check."""
