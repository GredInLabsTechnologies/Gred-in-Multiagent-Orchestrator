from __future__ import annotations

from typing import Callable

from ...ops_models import ProviderEntry
from ...providers.base import ProviderAdapter
from ...providers.cli_account import CliAccountAdapter
from ...providers.openai_compat import OpenAICompatAdapter
from .metadata import DEFAULT_BASE_URLS, OPENAI_COMPAT_ADAPTER_TYPES


def build_provider_adapter(
    *,
    entry: ProviderEntry,
    canonical_type: str,
    resolve_secret: Callable[[ProviderEntry], str | None],
) -> ProviderAdapter:
    if canonical_type in {"codex", "claude"} and str(entry.auth_mode or "").strip().lower() == "account":
        binary = "codex" if canonical_type == "codex" else "claude"
        return CliAccountAdapter(binary=binary)

    if canonical_type in OPENAI_COMPAT_ADAPTER_TYPES:
        if not entry.base_url:
            base_url = DEFAULT_BASE_URLS.get(canonical_type)
            if not base_url:
                raise ValueError(f"{canonical_type} provider missing base_url")
        else:
            base_url = entry.base_url
        return OpenAICompatAdapter(
            base_url=base_url,
            model=entry.model,
            api_key=resolve_secret(entry),
        )

    raise ValueError(f"Unsupported provider type: {entry.type}")
