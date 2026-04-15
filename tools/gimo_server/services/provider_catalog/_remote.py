from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Dict, List, Tuple

from ...ops_models import (
    NormalizedModelInfo,
    ProviderModelsCatalogResponse,
    ProviderValidateRequest,
    ProviderValidateResponse,
)
from ..providers.service import ProviderService
from ..providers.auth_service import ProviderAuthService
from ..providers.metadata import OPENAI_COMPAT_CATALOG_TYPES
from ._base import (
    _mock_mode_enabled,
    _fallback_models_for,
)
from ._openrouter_discovery import (
    get_ollama_recommended as _get_dynamic_ollama_recommended,
    FALLBACK_RECOMMENDED as _OLLAMA_FALLBACK,
)
from ._cli_account import _fetch_claude_cli_models

_logger = logging.getLogger("orchestrator.provider_catalog.remote")
_PRICING_CACHE: dict | None = None


def _load_pricing() -> dict:
    global _PRICING_CACHE
    if _PRICING_CACHE is not None:
        return _PRICING_CACHE
    try:
        path = Path(__file__).resolve().parent.parent.parent / "data" / "model_pricing.json"
        _PRICING_CACHE = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _logger.debug("Could not load model_pricing.json for metadata enrichment")
        _PRICING_CACHE = {}
    return _PRICING_CACHE


class RemoteFetchMixin:
    """Remote model fetching and catalog building."""

    @classmethod
    def _enrich_from_pricing(cls, models: List[NormalizedModelInfo]) -> List[NormalizedModelInfo]:
        """Fill missing quality_tier/context_window from model_pricing.json."""
        pricing = _load_pricing()
        if not pricing:
            return models
        enriched = []
        for m in models:
            if m.quality_tier is not None and m.context_window is not None:
                enriched.append(m)
                continue
            p = pricing.get(m.id) or {}
            # Alias resolution: try stripping -latest suffix, or match by prefix
            if not p:
                base = m.id.replace("-latest", "")
                for key in pricing:
                    if key.startswith(base):
                        p = pricing[key]
                        break
            updates = {}
            if m.quality_tier is None and p.get("quality_tier") is not None:
                updates["quality_tier"] = str(p["quality_tier"])
            if m.context_window is None and p.get("context_window") is not None:
                updates["context_window"] = p["context_window"]
            enriched.append(m.model_copy(update=updates) if updates else m)
        return enriched

    @classmethod
    async def list_installed_models(cls, provider_type: str) -> List[NormalizedModelInfo]:
        canonical = cls._canonical(provider_type)
        if canonical == "ollama_local":
            return await cls._ollama_list_installed()
        cfg = ProviderService.get_config()
        if not cfg:
            return []
        models: List[NormalizedModelInfo] = []
        for _pid, entry in cfg.providers.items():
            et = cls._canonical(entry.provider_type or entry.type)
            if et != canonical:
                continue
            models.append(cls._normalize_model(model_id=entry.model, installed=True, downloadable=False))
        dedup: Dict[str, NormalizedModelInfo] = {m.id: m for m in models}
        return list(dedup.values())

    @classmethod
    async def list_available_models(
        cls, provider_type: str, payload: ProviderValidateRequest | None = None
    ) -> Tuple[List[NormalizedModelInfo], List[str]]:
        canonical = cls._canonical(provider_type)
        warnings: List[str] = []

        if _mock_mode_enabled(payload):
            return cls._handle_mock_mode_catalog(canonical)

        if canonical == "ollama_local":
            # Dynamic discovery via OpenRouter (free, no API key).
            # Falls back to a static list if OpenRouter is unreachable.
            try:
                recommended = await _get_dynamic_ollama_recommended()
            except Exception:
                recommended = list(_OLLAMA_FALLBACK)
            return [
                cls._normalize_model(
                    model_id=m["id"], label=m.get("label"),
                    downloadable=True, quality_tier=m.get("quality_tier"),
                ) for m in recommended
            ], warnings

        # Claude account mode: try dynamic discovery via `claude api get /v1/models`.
        # Falls back to curated defaults if the CLI is unavailable or not authenticated.
        if canonical == "claude" and not (payload and payload.api_key):
            if shutil.which("claude"):
                live = await _fetch_claude_cli_models()
                if live:
                    return live, warnings
            return _fallback_models_for(canonical), warnings

        if canonical == "cloudflare-workers-ai":
            auth = payload or ProviderValidateRequest()
            remote = await cls._fetch_cloudflare_workers_ai_models(auth)
            if remote:
                return remote, warnings
            warnings.append(
                "Cloudflare Workers AI needs a base_url like https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1 "
                "and an API token with Workers AI permissions. Showing curated defaults."
            )
            return _fallback_models_for(canonical), warnings

        if canonical in {"replicate", "anthropic", "google", "mistral", "cohere"}:
            warnings.append("This provider may not expose a universal /models endpoint. Showing curated defaults.")
            return _fallback_models_for(canonical), warnings

        # Codex shares OpenAI's /v1/models endpoint. If account mode has no
        # resolvable credentials, try the OPENAI_API_KEY env var so that real
        # models are returned instead of the stale hardcoded fallback.
        if canonical == "codex" and not (payload and (payload.api_key or payload.account)):
            import os
            env_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if env_key:
                payload = ProviderValidateRequest(api_key=env_key)
            # Fall through to OPENAI_COMPAT_CATALOG_TYPES handler below.

        if canonical in {"vllm", "llama-cpp", "tgi", "azure-openai", "aws-bedrock", "vertex-ai"}:
            remote = await cls._fetch_remote_if_auth(canonical, payload)
            if remote:
                return remote, warnings
            warnings.append("This provider needs endpoint/credentials configuration to discover runtime models dynamically. Showing curated defaults.")
            return _fallback_models_for(canonical), warnings

        if canonical in OPENAI_COMPAT_CATALOG_TYPES:
            return await cls._handle_openai_compatible_catalog(canonical, payload, warnings)

        return [], warnings

    @classmethod
    def _handle_mock_mode_catalog(cls, canonical: str) -> Tuple[List[NormalizedModelInfo], List[str]]:
        if canonical == "ollama_local":
            return [
                cls._normalize_model(
                    model_id=m["id"], label=m.get("label"),
                    downloadable=True, quality_tier=m.get("quality_tier"),
                ) for m in _OLLAMA_FALLBACK
            ], ["Mock mode enabled: returning deterministic catalog without network."]
        mock_models = _fallback_models_for(canonical)
        if mock_models:
            return mock_models, ["Mock mode enabled: returning deterministic catalog without network."]
        return [cls._normalize_model(model_id=f"{canonical}-mock-model", label=f"{canonical} mock model")], [
            "Mock mode enabled: using synthetic model catalog for provider."
        ]

    @classmethod
    async def validate_credentials(
        cls, provider_type: str, payload: ProviderValidateRequest
    ) -> ProviderValidateResponse:
        canonical = cls._canonical(provider_type)
        cls.invalidate_cache(provider_type=canonical, reason="manual_test_connection")

        if _mock_mode_enabled(payload):
            mock_models, mock_warnings = await cls.list_available_models(canonical, payload=payload)
            response = ProviderValidateResponse(
                valid=True,
                health="ok",
                effective_model=(mock_models[0].id if mock_models else None),
                warnings=list(mock_warnings),
            )
            return cls._record_and_return_validation(canonical, response)

        if payload.account and str(payload.account).strip().lower().startswith("env:"):
            env_name = ProviderAuthService.parse_env_ref(payload.account)
            if env_name:
                payload = payload.model_copy(update={"account": (ProviderAuthService.resolve_env_expression(f"${{{env_name}}}") or "")})

        if canonical == "ollama_local":
            response = await cls._validate_ollama_local(canonical)
            return cls._record_and_return_validation(canonical, response)

        if canonical == "cloudflare-workers-ai":
            account_id = cls._cloudflare_account_id(payload.base_url or "")
            if not account_id:
                response = ProviderValidateResponse(
                    valid=False,
                    health="down",
                    warnings=["Cloudflare Workers AI requires an account-scoped OpenAI-compatible base_url."],
                    error_actionable="Set base_url to https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1.",
                )
                return cls._record_and_return_validation(canonical, response)
            if not payload.api_key and not payload.account:
                response = ProviderValidateResponse(
                    valid=False,
                    health="down",
                    warnings=["Missing Cloudflare API token."],
                    error_actionable="Provide an API token with Workers AI permissions for this provider.",
                )
                return cls._record_and_return_validation(canonical, response)

            remote = await cls._fetch_cloudflare_workers_ai_models(payload)
            if remote:
                response = ProviderValidateResponse(
                    valid=True,
                    health="ok",
                    effective_model=remote[0].id,
                    warnings=[],
                )
            else:
                response = ProviderValidateResponse(
                    valid=False,
                    health="degraded",
                    warnings=["Workers AI catalog lookup failed for the supplied account/token/base_url."],
                    error_actionable="Verify the account_id embedded in base_url and ensure the token has Workers AI - Read and Workers AI - Edit permissions.",
                )
            return cls._record_and_return_validation(canonical, response)

        # Codex/Claude account mode is CLI-native. Do not rely on remote /models.
        if canonical in {"codex", "claude"} and (payload.account is not None or payload.api_key is None):
            response = await cls._validate_cli_account_provider(canonical)
            return cls._record_and_return_validation(canonical, response)

        supports_account = bool(ProviderService.capabilities_for(canonical).get("supports_account_mode", False))
        if payload.account and not supports_account:
            response = ProviderValidateResponse(
                valid=False, health="down",
                warnings=["Account mode is not officially supported for this provider in current environment."],
                error_actionable="Use api_key mode for this provider.",
            )
            return cls._record_and_return_validation(canonical, response)

        if not payload.api_key and not payload.account:
            response = ProviderValidateResponse(
                valid=False, health="down", warnings=["Missing credentials payload."],
                error_actionable="Provide api_key or account according to selected auth mode.",
            )
            return cls._record_and_return_validation(canonical, response)

        remote = await cls._fetch_remote_models(canonical, payload)
        if remote:
            response = ProviderValidateResponse(valid=True, health="ok", effective_model=remote[0].id, warnings=[])
        else:
            response = ProviderValidateResponse(
                valid=False, health="degraded",
                warnings=["Remote API reachable check failed or returned empty catalog."],
                error_actionable="Verify base_url, api_key/org and provider account permissions.",
            )

        return cls._record_and_return_validation(canonical, response)

    @classmethod
    async def get_catalog(
        cls, provider_type: str, payload: ProviderValidateRequest | None = None
    ) -> ProviderModelsCatalogResponse:
        canonical = cls._canonical(provider_type)
        effective_payload = payload or cls._resolve_payload_from_provider_config(canonical)
        cache_key = cls._catalog_cache_key(provider_type=canonical, payload=effective_payload)
        now = time.time()
        cached = cls._CATALOG_CACHE.get(cache_key)
        if cached:
            expires_at, response = cached
            if now < expires_at:
                return response
            cls._CATALOG_CACHE.pop(cache_key, None)

        installed = await cls.list_installed_models(canonical)
        available, warnings = await cls.list_available_models(canonical, payload=effective_payload)

        # Enrich models with metadata from pricing DB when missing
        installed = cls._enrich_from_pricing(installed)
        available = cls._enrich_from_pricing(available)

        installed_ids = {m.id for m in installed}
        available_ids = {m.id for m in available}
        available = [m.model_copy(update={"installed": m.id in installed_ids}) for m in available]

        # For Ollama, the recommended list IS the available list (both come from
        # OpenRouter discovery).  Reuse instead of fetching twice to avoid
        # cold-start race conditions where the first fetch fails/returns empty.
        if canonical == "ollama_local":
            rec_raw = [
                {"id": m.id, "label": m.label, "quality_tier": m.quality_tier,
                 "context_window": m.context_window}
                for m in available
            ]
        else:
            rec_raw = []
        recommended = [
            cls._normalize_model(
                model_id=r["id"],
                label=r.get("label"),
                downloadable=(canonical == "ollama_local"),
                installed=r["id"] in installed_ids,
                quality_tier=r.get("quality_tier"),
                context_window=r.get("context_window"),
            )
            for r in rec_raw
            if r["id"] in available_ids or canonical == "ollama_local"
        ]

        response = ProviderModelsCatalogResponse(
            provider_type=canonical,  # type: ignore[arg-type]
            installed_models=installed,
            available_models=available,
            recommended_models=recommended,
            can_install=bool(ProviderService.capabilities_for(canonical).get("can_install", False)),
            install_method=cls._install_method_contract(canonical),  # type: ignore[arg-type]
            auth_modes_supported=cls.list_auth_modes(canonical),
            warnings=warnings,
        )
        ttl = cls._catalog_ttl_for(canonical)
        cls._CATALOG_CACHE[cache_key] = (now + ttl, response)
        return response
