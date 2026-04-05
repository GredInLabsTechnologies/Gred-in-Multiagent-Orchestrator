from __future__ import annotations

from typing import Callable

from ...ops_models import ProviderEntry
from ...providers.base import ProviderAdapter
from ...providers.cli_account import CliAccountAdapter
from ...providers.openai_compat import OpenAICompatAdapter
from ...providers.anthropic_adapter import AnthropicAdapter
from .metadata import DEFAULT_BASE_URLS, OPENAI_COMPAT_ADAPTER_TYPES

_ANTHROPIC_TYPES = {"anthropic", "claude"}


def build_provider_adapter(
    *,
    entry: ProviderEntry,
    canonical_type: str,
    resolve_secret: Callable[[ProviderEntry], str | None],
) -> ProviderAdapter:
    auth_mode = str(entry.auth_mode or "").strip().lower()

    if canonical_type in {"codex", "claude"} and auth_mode == "account":
        # HTTP-first: if an API key is available, prefer the HTTP adapter
        # over subprocess — avoids Windows cmd.exe 8191-char limit entirely.
        if canonical_type in _ANTHROPIC_TYPES:
            import os
            api_key = resolve_secret(entry) or os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if api_key:
                base_url = entry.base_url or DEFAULT_BASE_URLS.get(canonical_type, "https://api.anthropic.com")
                if base_url.endswith("/v1"):
                    base_url = base_url.removesuffix("/v1")
                return AnthropicAdapter(base_url=base_url, model=entry.model, api_key=api_key)
            # SAGP: Claude CLI account mode is DEPRECATED — violates Anthropic's
            # April 2026 third-party harness policy.  Codex CLI is unaffected.
            import logging as _logging
            _logging.getLogger("orchestrator.providers").warning(
                "[SAGP] CliAccountAdapter for Claude is deprecated. "
                "Set ANTHROPIC_API_KEY or use GIMO as MCP server from Claude App."
            )
            raise ValueError(
                "Claude CLI account mode is no longer supported (Anthropic April 2026 policy). "
                "Set ANTHROPIC_API_KEY for pay-as-you-go API access, or use GIMO as an MCP "
                "server from within Claude App/Code (first-party, allowed)."
            )
        return CliAccountAdapter(binary="codex")

    # Anthropic/Claude with API key → dedicated adapter (x-api-key + /v1/messages)
    if canonical_type in _ANTHROPIC_TYPES and auth_mode != "account":
        base_url = entry.base_url or DEFAULT_BASE_URLS.get(canonical_type, "https://api.anthropic.com")
        if base_url.endswith("/v1"):
            base_url = base_url.removesuffix("/v1")
        return AnthropicAdapter(
            base_url=base_url,
            model=entry.model,
            api_key=resolve_secret(entry),
        )

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
