"""Adapter for Anthropic Messages API (Claude models).

Anthropic uses a different auth scheme (x-api-key header) and endpoint
(/messages) than OpenAI-compatible APIs. This adapter handles the
translation so GIMO can use Claude models via API key.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from .base import ProviderAdapter

logger = logging.getLogger(__name__)


class AnthropicAdapter(ProviderAdapter):
    """Adapter for Anthropic's Messages API."""

    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(
        self,
        *,
        base_url: str = "https://api.anthropic.com",
        model: str,
        api_key: Optional[str] = None,
        timeout_seconds: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.ANTHROPIC_VERSION,
        }
        key = (self.api_key or "").strip()
        if key:
            headers["x-api-key"] = key
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _to_anthropic_messages(messages: List[Dict[str, Any]]) -> tuple[str | None, List[Dict[str, Any]]]:
        """Convert OpenAI-format messages to Anthropic format.

        Returns (system_prompt, messages) where system is extracted
        from any system role messages.
        """
        system_parts: list[str] = []
        anthropic_msgs: list[dict] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_parts.append(str(content))
            elif role == "assistant":
                # Handle tool_calls in assistant messages (for multi-turn tool use)
                if msg.get("tool_calls"):
                    blocks: list[dict] = []
                    if content:
                        blocks.append({"type": "text", "text": str(content)})
                    for tc in msg["tool_calls"]:
                        fn = tc.get("function", {})
                        args = fn.get("arguments", "{}")
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {"raw": args}
                        blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": fn.get("name", ""),
                            "input": args,
                        })
                    anthropic_msgs.append({"role": "assistant", "content": blocks})
                else:
                    anthropic_msgs.append({"role": "assistant", "content": str(content)})
            elif role == "tool":
                # Tool result messages
                anthropic_msgs.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": str(content),
                    }],
                })
            else:
                anthropic_msgs.append({"role": "user", "content": str(content)})

        system = "\n\n".join(system_parts) if system_parts else None
        return system, anthropic_msgs

    @staticmethod
    def _to_anthropic_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI tool format to Anthropic tool format."""
        anthropic_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                fn = tool["function"]
                anthropic_tools.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
        return anthropic_tools

    @staticmethod
    def _parse_response(data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Anthropic response to GIMO's normalized format."""
        content_blocks = data.get("content", [])
        text_parts: list[str] = []
        tool_calls: list[dict] = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                args = block.get("input", {})
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
                    },
                })

        usage_data = data.get("usage", {})
        stop_reason = data.get("stop_reason", "end_turn")
        finish_reason = "tool_calls" if stop_reason == "tool_use" else "stop"

        return {
            "content": "\n".join(text_parts) if text_parts else None,
            "tool_calls": tool_calls,
            "usage": {
                "prompt_tokens": usage_data.get("input_tokens", 0),
                "completion_tokens": usage_data.get("output_tokens", 0),
                "total_tokens": usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            },
            "finish_reason": finish_reason,
        }

    async def generate(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        sys_hint = context.get("system") if isinstance(context, dict) else None
        model = context.get("model") or self.model

        payload: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
            "temperature": 0.2,
        }
        if sys_hint:
            payload["system"] = str(sys_hint)

        client = self._get_client()
        resp = await client.post(
            f"{self.base_url}/v1/messages",
            headers=self._headers(),
            json=payload,
        )
        resp.raise_for_status()
        result = self._parse_response(resp.json())
        return {"content": result["content"] or "", "usage": result["usage"]}

    async def _raw_chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        system, anthropic_msgs = self._to_anthropic_messages(messages)
        model = self.model

        payload: Dict[str, Any] = {
            "model": model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = self._to_anthropic_tools(tools)

        client = self._get_client()
        resp = await client.post(
            f"{self.base_url}/v1/messages",
            headers=self._headers(),
            json=payload,
        )
        resp.raise_for_status()
        return self._parse_response(resp.json())

    async def health_check(self) -> bool:
        """Check if Anthropic API is reachable with valid credentials."""
        client = self._get_client()
        try:
            # Minimal request to verify auth
            resp = await client.post(
                f"{self.base_url}/v1/messages",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
            )
            return 200 <= resp.status_code < 300
        except Exception:
            return False
