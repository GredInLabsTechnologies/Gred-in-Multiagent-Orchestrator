from __future__ import annotations

import shutil
from typing import Dict, List, Tuple

from ...ops_models import (
    NormalizedModelInfo,
    ProviderValidateRequest,
    ProviderValidateResponse,
)
from ..provider_catalog_ollama_helpers import (
    ensure_ollama_ready as _ensure_ollama_ready_helper,
    ollama_health as _ollama_health_helper,
    ollama_list_installed as _ollama_list_installed_helper,
)
from ._base import (
    ProviderCatalogBase,
    _OLLAMA_RECOMMENDED,
    _mock_mode_enabled,
    _fallback_models_for,
)


class OllamaMixin:
    """Ollama-specific methods: list installed, health, validate, recommended."""

    @classmethod
    async def _ollama_list_installed(cls) -> List[NormalizedModelInfo]:
        return await _ollama_list_installed_helper(cls._normalize_model)

    @classmethod
    async def ensure_ollama_ready(cls) -> bool:
        return await _ensure_ollama_ready_helper()

    @classmethod
    async def _ollama_health(cls) -> bool:
        return await _ollama_health_helper()

    @classmethod
    async def _validate_ollama_local(cls, canonical: str) -> ProviderValidateResponse:
        installed = shutil.which("ollama") is not None
        if not installed:
            return ProviderValidateResponse(
                valid=False,
                health="down",
                warnings=["Ollama command not found."],
                error_actionable="Install Ollama and ensure it is available in PATH.",
            )
        ok = await cls._ollama_health()
        return ProviderValidateResponse(
            valid=ok,
            health="ok" if ok else "degraded",
            warnings=[] if ok else ["Ollama runtime not reachable at local endpoint."],
            error_actionable=None if ok else "Start Ollama daemon and retry validation.",
        )
