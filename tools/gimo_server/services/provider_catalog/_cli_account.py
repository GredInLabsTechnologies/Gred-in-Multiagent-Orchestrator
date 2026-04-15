from __future__ import annotations

import asyncio
import json as _json
import logging
import shutil
from typing import List

from ...ops_models import (
    NormalizedModelInfo,
    ProviderValidateResponse,
)
from ._base import (
    _run_sync,
    _fallback_models_for,
)

logger = logging.getLogger("orchestrator.provider_catalog.cli_account")


async def _fetch_claude_cli_models() -> List[NormalizedModelInfo]:
    """Discover Claude models dynamically via `claude api get /v1/models`.

    Runs from the server process (no CLAUDECODE guard) using run_in_executor
    so it doesn't block the event loop.
    """
    loop = asyncio.get_running_loop()
    try:
        rc, output = await asyncio.wait_for(
            loop.run_in_executor(None, _run_sync, ["claude", "api", "get", "/v1/models"]),
            timeout=12.0,
        )
    except (asyncio.TimeoutError, TimeoutError):
        return []
    except Exception:
        return []

    if rc != 0 or not output:
        return []

    try:
        data = _json.loads(output)
        items = data.get("data", []) if isinstance(data, dict) else []
        models: List[NormalizedModelInfo] = []
        for item in items:
            model_id = str(item.get("id") or "").strip()
            if not model_id:
                continue
            display_name = str(item.get("display_name") or item.get("name") or model_id)
            context_window = item.get("context_window") or None
            models.append(NormalizedModelInfo(
                id=model_id,
                label=display_name,
                context_window=context_window,
                installed=False,
                downloadable=False,
            ))
        return models
    except Exception:
        return []


class CliAccountMixin:
    """CLI-based account validation (Codex/Claude)."""

    @classmethod
    async def _validate_cli_account_provider(cls, canonical: str) -> ProviderValidateResponse:
        """Validate CLI-native account mode providers (Codex/Claude).

        Uses the auth services (run_in_executor + subprocess.Popen) to avoid
        asyncio.create_subprocess_* which is unsupported on Windows SelectorEventLoop.
        """
        install_hint = "npm install -g @openai/codex" if canonical == "codex" else "npm install -g @anthropic-ai/claude-code"
        binary = "codex" if canonical == "codex" else "claude"

        if shutil.which(binary) is None:
            return ProviderValidateResponse(
                valid=False,
                health="down",
                warnings=[f"{binary} CLI not found in PATH."],
                error_actionable=f"Install {binary} CLI and retry: {install_hint}",
            )

        # Use auth services — they use run_in_executor + Popen which works on Windows.
        try:
            if canonical == "codex":
                from ..codex_auth_service import CodexAuthService
                status = await CodexAuthService.get_auth_status()
            else:
                from ..claude_auth_service import ClaudeAuthService
                status = await ClaudeAuthService.get_auth_status()
        except Exception as exc:
            logger.warning("_validate_cli_account_provider auth status error: %s", exc)
            status = {"authenticated": False, "detail": str(exc)}

        recommended = _fallback_models_for(canonical)
        effective_model = recommended[0].id if recommended else None

        if status.get("authenticated"):
            method = status.get("method") or "account"
            return ProviderValidateResponse(
                valid=True,
                health="ok",
                effective_model=effective_model,
                warnings=[f"Validated via local {binary} CLI session ({method})."],
            )

        # CLI is installed but auth status unknown/false — still mark as degraded not down
        detail = status.get("detail") or ""
        return ProviderValidateResponse(
            valid=False,
            health="degraded",
            effective_model=None,
            warnings=[f"{binary} CLI found but session not authenticated. {detail}".strip()],
            error_actionable=f"Run '{binary} login' to authenticate.",
        )
