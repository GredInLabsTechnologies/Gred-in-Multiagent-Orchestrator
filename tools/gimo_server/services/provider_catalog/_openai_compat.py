from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple
from urllib.parse import urlsplit

import httpx

from ...ops_models import (
    NormalizedModelInfo,
    ProviderValidateRequest,
)
from ..ops import OpsService
from ..providers.metadata import OPENAI_COMPAT_CATALOG_TYPES, REMOTE_MODELS_BASE_URLS
from ._base import (
    _fallback_models_for,
)


class OpenAICompatMixin:
    """OpenAI-compatible provider methods: fetch remote models, parse items, infer capabilities."""

    _CLOUDFLARE_ACCOUNT_RE = re.compile(r"/accounts/(?P<account_id>[^/]+)/ai(?:/|$)")
    _CLOUDFLARE_MODEL_SEARCH_TERMS: Tuple[str, ...] = (
        "qwen3-30b-a3b-fp8",
        "qwen2.5-coder-32b-instruct",
        "gpt-oss-120b",
        "gpt-oss-20b",
        "kimi-k2.5",
    )

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
    def _cloudflare_api_origin(cls, base_url: str) -> str:
        parsed = urlsplit((base_url or "").strip())
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return "https://api.cloudflare.com"

    @classmethod
    def _cloudflare_account_id(cls, base_url: str) -> str | None:
        match = cls._CLOUDFLARE_ACCOUNT_RE.search((base_url or "").strip())
        if not match:
            return None
        account_id = str(match.group("account_id") or "").strip()
        return account_id or None

    @staticmethod
    def _cloudflare_property_map(item: Dict[str, Any]) -> Dict[str, Any]:
        props: Dict[str, Any] = {}
        for prop in item.get("properties", []) or []:
            if not isinstance(prop, dict):
                continue
            key = str(prop.get("property_id") or "").strip()
            if key:
                props[key] = prop.get("value")
        return props

    @classmethod
    def _parse_cloudflare_workers_ai_model_item(cls, item: Dict[str, Any]) -> NormalizedModelInfo | None:
        model_id = str(item.get("name") or "").strip()
        if not model_id:
            return None
        description = str(item.get("description") or "").strip() or None
        props = cls._cloudflare_property_map(item)
        context_window = cls._safe_int(props.get("context_window"))
        capabilities = cls._infer_capabilities(model_id=model_id, description=description)
        if str(props.get("function_calling") or "").strip().lower() == "true" and "tools" not in capabilities:
            capabilities.append("tools")
        if str(props.get("reasoning") or "").strip().lower() == "true" and "reasoning" not in capabilities:
            capabilities.append("reasoning")
        priors = cls._build_prior_scores(
            model_id=model_id,
            capabilities=capabilities,
            context_window=context_window,
        )
        OpsService.seed_model_priors(
            provider_type="cloudflare-workers-ai",
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
            label=model_id,
            downloadable=False,
            context_window=context_window,
            description=description,
            capabilities=capabilities,
            weakness=cls._infer_weakness(model_id),
        )

    @classmethod
    async def _fetch_cloudflare_workers_ai_models(
        cls,
        payload: ProviderValidateRequest,
    ) -> List[NormalizedModelInfo]:
        auth_token = (payload.api_key or payload.account or "").strip()
        account_id = cls._cloudflare_account_id(payload.base_url or "")
        if not auth_token or not account_id:
            return []

        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }
        endpoint = (
            f"{cls._cloudflare_api_origin(payload.base_url or '')}"
            f"/client/v4/accounts/{account_id}/ai/models/search"
        )
        seen: Dict[str, NormalizedModelInfo] = {}

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                for term in cls._CLOUDFLARE_MODEL_SEARCH_TERMS:
                    resp = await client.get(
                        endpoint,
                        headers=headers,
                        params={
                            "task": "Text Generation",
                            "search": term,
                            "per_page": 5,
                            "hide_experimental": True,
                        },
                    )
                    if resp.status_code < 200 or resp.status_code >= 300:
                        continue
                    data = resp.json()
                    items = data.get("result", []) if isinstance(data, dict) else []
                    for item in items:
                        model = cls._parse_cloudflare_workers_ai_model_item(item)
                        if model is not None:
                            seen.setdefault(model.id, model)
        except Exception:
            return []

        return list(seen.values())

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
