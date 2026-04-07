"""Backend-authoritative provider diagnostics service.

R17 Cluster E.2 — replaces inline provider probing previously duplicated in
``gimo_cli/commands/auth.py::doctor`` and ``gimo_cli/commands/providers.py::
providers_test``. The CLI surfaces are now thin clients of
``GET /ops/providers/diagnostics``.

The probe combines, per provider:
    - connector reachability (``ProviderService.connector_health``)
    - normalized auth status (``CodexAuthService`` / ``ClaudeAuthService`` /
      vault-stored API key for openai_compat providers).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from tools.gimo_server.models import ProviderDiagnosticEntry, ProviderDiagnosticReport


class ProviderDiagnosticsService:
    """Compute a unified diagnostics report for all configured providers."""

    @classmethod
    async def report(cls) -> ProviderDiagnosticReport:
        from tools.gimo_server.services.provider_service import ProviderService

        cfg = ProviderService.get_config()
        if not cfg:
            return ProviderDiagnosticReport(entries=[], total=0, healthy=0)

        provider_ids: List[str] = sorted(cfg.providers.keys())
        entries: List[ProviderDiagnosticEntry] = []
        for pid in provider_ids:
            entries.append(await cls._probe_one(pid))

        healthy = sum(1 for e in entries if e.reachable and e.auth_status == "ok")
        return ProviderDiagnosticReport(
            entries=entries,
            total=len(entries),
            healthy=healthy,
        )

    @classmethod
    async def _probe_one(cls, provider_id: str) -> ProviderDiagnosticEntry:
        from tools.gimo_server.services.provider_service import ProviderService

        started = time.perf_counter()
        reachable = False
        details: Dict[str, Any] = {}
        error: Optional[str] = None

        try:
            health = await ProviderService.connector_health("openai_compat", provider_id=provider_id)
            reachable = bool(health.get("healthy"))
            details = health.get("details") or {}
        except Exception as exc:  # pragma: no cover - defensive
            error = f"health probe failed: {exc}"

        auth_status, method, auth_error = await cls._auth_probe(provider_id)
        if auth_error and not error:
            error = auth_error

        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return ProviderDiagnosticEntry(
            provider_id=provider_id,
            reachable=reachable,
            auth_status=auth_status,
            method=method,
            latency_ms=latency_ms,
            error=error,
            details=details,
        )

    @classmethod
    async def _auth_probe(cls, provider_id: str):
        """Return ``(auth_status, method, error)``.

        Mirrors ``provider_auth_router._enrich_with_vault_key`` semantics so
        the CLI surfaces see the same answer the auth-status routes return.
        """
        from tools.gimo_server.services.codex_auth_service import CodexAuthService
        from tools.gimo_server.services.claude_auth_service import ClaudeAuthService
        from tools.gimo_server.services.providers.secret_store import get_secret

        normalized = (provider_id or "").lower()
        try:
            if normalized in {"codex", "codex-account"}:
                data = await CodexAuthService.get_auth_status()
            elif normalized in {"claude", "claude-account", "anthropic"}:
                data = await ClaudeAuthService.get_auth_status()
            else:
                data = {}
        except Exception as exc:
            return ("error", None, f"auth probe failed: {exc}")

        if data.get("authenticated"):
            return ("ok", str(data.get("method") or "cli"), None)

        # Vault-stored API key fallback (mirrors _enrich_with_vault_key)
        raw = normalized
        variants = {raw, raw.replace("-", "_"), f"{raw}-account", f"{raw}_account"}
        for v in variants:
            env_name = f"ORCH_PROVIDER_{v.upper()}_API_KEY"
            if get_secret(env_name):
                return ("ok", "api_key", None)

        if data.get("expired"):
            return ("expired", str(data.get("method") or "cli"), None)
        return ("missing", None, None)
