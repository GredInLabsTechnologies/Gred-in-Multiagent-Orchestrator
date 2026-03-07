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
        timeout_seconds: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        # OpenAI: Authorization required; Ollama/LM Studio: typically ignored if present.
        key = (self.api_key or "").strip()
        if key and not key.startswith("${"):
            headers["Authorization"] = f"Bearer {key}"
        return headers

    @staticmethod
    def _truthy_env(value: Optional[str]) -> bool:
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _is_mock_token(value: Optional[str]) -> bool:
        token = str(value or "").strip().lower()
        return token.startswith("mock:") or token.startswith("mock_") or token == "mock"

    def _mock_mode_enabled(self, context: Optional[Dict[str, Any]] = None) -> bool:
        if self._truthy_env(os.environ.get("ORCH_PROVIDER_MOCK_MODE")):
            return True
        if self._is_mock_token(self.api_key):
            return True
        if isinstance(context, dict):
            if self._is_mock_token(context.get("api_key")):
                return True
            if self._is_mock_token(context.get("account")):
                return True
        return False

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def generate(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if self._mock_mode_enabled(context):
            model = str((context or {}).get("model") or self.model)
            content = f"[MOCK:{model}] {prompt[:200]}"
            prompt_tokens = max(1, len(prompt.split()))
            completion_tokens = max(4, min(64, prompt_tokens // 2 + 4))
            return {
                "content": content,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            }

        # Keep context simple and safe.
        sys_hint = context.get("system") if isinstance(context, dict) else None
        messages = []
        if sys_hint:
            messages.append({"role": "system", "content": str(sys_hint)})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": context.get("model") or self.model,
            "messages": messages,
            "temperature": 0.2,
        }

        client = self._get_client()
        resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {"prompt_tokens": 0, "completion_tokens": 0})
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            # Fall back to raw JSON if provider does not follow schema
            content = str(data)

        return {
            "content": content,
            "usage": usage
        }

    async def health_check(self) -> bool:
        if self._mock_mode_enabled({}):
            return True
        # Best effort: try GET /models (OpenAI style). If fails, return False.
        client = self._get_client()
        try:
            resp = await client.get(
                f"{self.base_url}/models",
                headers=self._headers(),
            )
            return 200 <= resp.status_code < 300
        except Exception:
            return False
