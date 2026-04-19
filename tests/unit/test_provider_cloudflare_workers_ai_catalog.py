from __future__ import annotations

import asyncio

from tools.gimo_server.ops_models import ProviderValidateRequest
from tools.gimo_server.services.provider_catalog.service import ProviderCatalogService


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _AsyncClientStub:
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> "_AsyncClientStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str, headers: dict | None = None, params: dict | None = None) -> _Response:
        self.calls.append((url, params or {}))
        return _Response(
            200,
            {
                "success": True,
                "result": [
                    {
                        "name": "@cf/qwen/qwen3-30b-a3b-fp8",
                        "description": "Qwen3 agent model",
                        "properties": [
                            {"property_id": "context_window", "value": "32768"},
                            {"property_id": "function_calling", "value": "true"},
                            {"property_id": "reasoning", "value": "true"},
                        ],
                    }
                ],
                "errors": [],
                "messages": [],
            },
        )


def test_validate_credentials_cloudflare_workers_ai_requires_account_scoped_base_url() -> None:
    payload = ProviderValidateRequest(api_key="cf-token-1234567890", base_url="https://api.cloudflare.com/client/v4/ai/v1")

    result = asyncio.run(ProviderCatalogService.validate_credentials("cloudflare-workers-ai", payload))

    assert result.valid is False
    assert result.health == "down"
    assert "<ACCOUNT_ID>" in (result.error_actionable or "")


def test_validate_credentials_cloudflare_workers_ai_uses_live_catalog_lookup(monkeypatch) -> None:
    monkeypatch.setattr(
        "tools.gimo_server.services.provider_catalog._openai_compat.httpx.AsyncClient",
        _AsyncClientStub,
    )
    payload = ProviderValidateRequest(
        api_key="cf-token-1234567890",
        base_url="https://api.cloudflare.com/client/v4/accounts/test-account/ai/v1",
    )

    result = asyncio.run(ProviderCatalogService.validate_credentials("cloudflare-workers-ai", payload))

    assert result.valid is True
    assert result.health == "ok"
    assert result.effective_model == "@cf/qwen/qwen3-30b-a3b-fp8"
