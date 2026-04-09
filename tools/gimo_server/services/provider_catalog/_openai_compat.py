from __future__ import annotations

from typing import Any, Dict, List, Tuple

import httpx

from ...ops_models import (
    NormalizedModelInfo,
    ProviderValidateRequest,
)
from ..ops_service import OpsService
from ..providers.metadata import OPENAI_COMPAT_CATALOG_TYPES, REMOTE_MODELS_BASE_URLS
from ._base import (
    ProviderCatalogBase,
    _fallback_models_for,
)


class OpenAICompatMixin:
    """OpenAI-compatible provider methods: fetch remote models, parse items, infer capabilities."""

    @classmethod
    def _parse_remote_model_item(cls, provider_type: str, item: Dict[str, Any]) -> NormalizedModelInfo | None:
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            return None
        description = str(item.get("description") or "").strip() or None
        context_window = cls._safe_int(item.get("context_length"))
        capabilities = cls._infer_capabilities(model_id=model_id, description=description)
        priors = cls._build_prior_scores(
            model_id=model_id,
            capabilities=capabilities,
            context_window=context_window,
        )
        OpsService.seed_model_priors(
            provider_type=provider_type,
            model_id=model_id,
            prior_scores=priors,
            metadata={
                "description": description or "",
                "context_window": context_window,
                "capabilities": capabilities,
            },
        )
        return cls._normalize_model(
            model_id=model_id,
            label=str(item.get("name") or item.get("id") or model_id),
            downloadable=False,
            context_window=context_window,
            description=description,
            capabilities=capabilities,
            weakness=cls._infer_weakness(model_id),
        )

    @classmethod
    async def _fetch_remote_models(
        cls, provider_type: str, payload: ProviderValidateRequest
    ) -> List[NormalizedModelInfo]:
        base_url = (payload.base_url or "").strip()
        if not base_url:
            base_url = REMOTE_MODELS_BASE_URLS.get(provider_type, "")
        if not base_url:
            return []

        headers = {"Content-Type": "application/json"}
        if payload.api_key:
            headers["Authorization"] = f"Bearer {payload.api_key}"
        elif payload.account:
            headers["Authorization"] = f"Bearer {payload.account}"
        if payload.org:
            headers["OpenAI-Organization"] = payload.org

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
                if resp.status_code < 200 or resp.status_code >= 300:
                    return []
                data = resp.json()
                items = data.get("data", []) if isinstance(data, dict) else []
                out = [m for item in items if (m := cls._parse_remote_model_item(provider_type, item)) is not None]
                return out
        except Exception:
            return []

    @classmethod
    async def _handle_openai_compatible_catalog(cls, canonical: str, payload: ProviderValidateRequest | None, warnings: List[str]) -> Tuple[List[NormalizedModelInfo], List[str]]:
        auth = payload or ProviderValidateRequest()
        if canonical == "openrouter" and not (auth.api_key or auth.account):
            remote = await cls._fetch_remote_models(canonical, auth)
            if remote:
                warnings.append("Using OpenRouter public catalog without credentials.")
                return remote, warnings
            warnings.append("OpenRouter public catalog unavailable. Showing curated defaults.")
            return _fallback_models_for(canonical), warnings

        if not (auth.api_key or auth.account):
            warnings.append("Authentication is required to fetch remote model catalog.")
            return _fallback_models_for(canonical), warnings

        remote = await cls._fetch_remote_models(canonical, auth)
        if remote:
            return remote, warnings
        warnings.append("Could not fetch remote models from provider API.")
        return _fallback_models_for(canonical), warnings

    @classmethod
    async def _fetch_remote_if_auth(cls, canonical: str, payload: ProviderValidateRequest | None) -> List[NormalizedModelInfo]:
        auth = payload or ProviderValidateRequest()
        if (auth.base_url and (auth.api_key or auth.account)) or auth.base_url:
            return await cls._fetch_remote_models(canonical, auth)
        return []
