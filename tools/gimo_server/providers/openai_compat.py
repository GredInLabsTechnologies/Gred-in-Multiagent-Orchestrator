from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from .base import ProviderAdapter


class OpenAICompatAdapter(ProviderAdapter):
    """Adapter for OpenAI-compatible chat completions APIs.

    Works with OpenAI, LM Studio, Ollama (when exposing /v1).
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        timeout_seconds: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        # OpenAI: Authorization required; Ollama/LM Studio: typically ignored if present.
        key = (self.api_key or "").strip()
        if key and not key.startswith("${"):
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def generate(self, prompt: str, context: Dict[str, Any]) -> str:
        # Keep context simple and safe.
        sys_hint = context.get("system") if isinstance(context, dict) else None
        messages = []
        if sys_hint:
            messages.append({"role": "system", "content": str(sys_hint)})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            try:
                return data["choices"][0]["message"]["content"]
            except Exception:
                # Fall back to raw JSON if provider does not follow schema
                return str(data)

    async def health_check(self) -> bool:
        # Best effort: try GET /models (OpenAI style). If fails, return False.
        async with httpx.AsyncClient(timeout=5) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers=self._headers(),
                )
                return 200 <= resp.status_code < 300
            except Exception:
                return False
