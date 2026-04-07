from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.codex_auth_service import CodexAuthService
from tools.gimo_server.services.claude_auth_service import ClaudeAuthService
from tools.gimo_server.services.provider_account_service import ProviderAccountService
from tools.gimo_server.services.providers.provider_diagnostics_service import (
    ProviderDiagnosticsService,
)
from tools.gimo_server.models import ProviderDiagnosticReport
from .common import _require_role, _actor_label

router = APIRouter()


@router.get("/providers/diagnostics", response_model=ProviderDiagnosticReport)
async def providers_diagnostics(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """R17 Cluster E.2 — backend-authoritative provider diagnostics.

    Single source of truth for ``gimo doctor`` and ``gimo providers test``.
    Probes connector reachability + auth status for every configured provider.
    """
    _require_role(auth, "operator")
    report = await ProviderDiagnosticsService.report()
    audit_log(
        "OPS",
        "/ops/providers/diagnostics",
        f"total={report.total} healthy={report.healthy}",
        operation="READ",
        actor=_actor_label(auth),
    )
    return report


def _enrich_with_vault_key(provider: str, data: dict) -> dict:
    """Check if an API key is stored in the encrypted vault for this provider."""
    from tools.gimo_server.services.providers.secret_store import get_secret

    raw = str(provider or "").strip().lower()
    # Try multiple naming conventions (guiones, guiones bajos, con/sin -account)
    variants = {raw, raw.replace("-", "_"), f"{raw}-account", f"{raw}_account"}
    candidates = []
    for v in variants:
        candidates.append(f"ORCH_PROVIDER_{v.upper()}_API_KEY")
    # Deduplicate preserving order
    seen = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]
    for env_name in candidates:
        stored = get_secret(env_name)
        if stored:
            data = dict(data)
            data["authenticated"] = True
            data["method"] = "api_key"
            data["detail"] = f"API key stored (vault: {env_name})"
            return data
    return data


def _resolve_cli_auth_provider(provider: str):
    normalized = str(provider or "").strip().lower()
    if normalized == "codex":
        return CodexAuthService
    if normalized == "claude":
        return ClaudeAuthService
    raise HTTPException(status_code=404, detail="Unsupported provider")


@router.post("/connectors/codex/login")
async def codex_device_login(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    import logging, traceback
    _log = logging.getLogger("orchestrator.codex_login")
    _require_role(auth, "operator")
    try:
        _log.info(">>> codex_device_login called")
        data = await CodexAuthService.start_device_flow()
        _log.info(">>> codex_device_login result: %s", data)
        audit_log("OPS", "/ops/connectors/codex/login", "auth_flow_started", operation="READ", actor=_actor_label(auth))
        return data
    except Exception:
        _log.error(">>> codex_device_login EXCEPTION:\n%s", traceback.format_exc())
        raise


@router.post("/provider/codex/device-login")
async def codex_device_login_legacy(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Backward-compatible alias for legacy clients.

    Kept for production safety while the UI and external clients migrate to:
    POST /ops/connectors/codex/login
    """
    _require_role(auth, "operator")
    data = await CodexAuthService.start_device_flow()
    audit_log(
        "OPS",
        "/ops/provider/codex/device-login",
        "auth_flow_started",
        operation="READ",
        actor=_actor_label(auth),
    )
    return data


@router.get("/connectors/codex/auth-status")
async def codex_auth_status(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await CodexAuthService.get_auth_status()
    if not data.get("authenticated"):
        data = _enrich_with_vault_key("codex", data)
    return data


@router.post("/connectors/codex/logout")
async def codex_logout(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await CodexAuthService.logout()
    audit_log("OPS", "/ops/connectors/codex/logout", "logout", operation="WRITE", actor=_actor_label(auth))
    return data


@router.get("/connectors/claude/auth-status")
async def claude_auth_status(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await ClaudeAuthService.get_auth_status()
    if not data.get("authenticated"):
        data = _enrich_with_vault_key("claude", data)
    return data


@router.get("/connectors/{provider}/auth-status")
async def provider_auth_status(
    provider: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    service = _resolve_cli_auth_provider(provider)
    data = await service.get_auth_status()
    # Enrich: check if an API key is stored in the vault for this provider
    if not data.get("authenticated"):
        data = _enrich_with_vault_key(provider, data)
    return data


@router.post("/connectors/claude/logout")
async def claude_logout(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await ClaudeAuthService.logout()
    audit_log("OPS", "/ops/connectors/claude/logout", "logout", operation="WRITE", actor=_actor_label(auth))
    return data


@router.post("/connectors/{provider}/logout")
async def provider_logout(
    provider: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    service = _resolve_cli_auth_provider(provider)
    data = await service.logout()
    audit_log("OPS", f"/ops/connectors/{provider}/logout", "logout", operation="WRITE", actor=_actor_label(auth))
    return data


@router.post("/connectors/claude/login")
async def claude_login_start(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await ClaudeAuthService.start_login_flow()
    audit_log("OPS", "/ops/connectors/claude/login", "auth_flow_started", operation="READ", actor=_actor_label(auth))
    return data


@router.post("/connectors/account/login/start")
async def account_login_start(
    request: Request,
    body: dict,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Phase 6.5: start account-mode device flow and persist flow state."""
    _require_role(auth, "operator")
    provider_id = str(body.get("provider_id") or "").strip() or None

    cfg = ProviderService.get_config()
    if not cfg:
        raise HTTPException(status_code=404, detail="Provider config missing")
    pid = provider_id or cfg.active
    if pid not in cfg.providers:
        raise HTTPException(status_code=404, detail="Unknown provider")

    entry = cfg.providers[pid]
    canonical = ProviderService.normalize_provider_type(entry.provider_type or entry.type)
    if canonical == "codex":
        data = await CodexAuthService.start_device_flow()
    elif canonical == "claude":
        data = await ClaudeAuthService.start_login_flow()
    else:
        raise HTTPException(status_code=400, detail="account mode is only supported for codex/claude")

    if str(data.get("status") or "").lower() == "error":
        return data

    flow = ProviderAccountService.start_flow(
        provider_id=pid,
        verification_url=str(data.get("verification_url") or ""),
        user_code=str(data.get("user_code") or ""),
        poll_id=str(data.get("poll_id") or ""),
    )
    audit_log(
        "OPS",
        "/ops/connectors/account/login/start",
        f"provider_connected:{flow.get('provider_id')}",
        operation="WRITE",
        actor=_actor_label(auth),
    )
    return {
        "status": "PROVIDER_AUTH_PENDING",
        "flow_id": flow.get("flow_id"),
        "provider_id": flow.get("provider_id"),
        "verification_url": flow.get("verification_url"),
        "user_code": flow.get("user_code"),
        "poll_id": flow.get("poll_id"),
    }


@router.get("/connectors/account/login/{flow_id}", responses={404: {"description": "Not Found"}})
async def account_login_status(
    request: Request,
    flow_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    try:
        flow = ProviderAccountService.get_flow(flow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return flow


@router.post("/connectors/account/refresh", responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}})
async def account_refresh(
    request: Request,
    body: dict,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Phase 6.5: refresh account session and keep auth_ref in secure env indirection."""
    _require_role(auth, "operator")
    provider_id = str(body.get("provider_id") or "").strip()
    if not provider_id:
        raise HTTPException(status_code=400, detail="provider_id is required")

    account_token = body.get("account_token")
    try:
        result = ProviderAccountService.refresh_account_ref(
            provider_id=provider_id,
            account_token=str(account_token) if account_token else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    audit_log(
        "OPS",
        "/ops/connectors/account/refresh",
        f"provider_token_refreshed:{provider_id}",
        operation="WRITE",
        actor=_actor_label(auth),
    )
    return result


@router.post("/connectors/account/logout", responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}})
async def account_logout(
    request: Request,
    body: dict,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    provider_id = str(body.get("provider_id") or "").strip()
    if not provider_id:
        raise HTTPException(status_code=400, detail="provider_id is required")
    try:
        result = ProviderAccountService.logout(provider_id=provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log(
        "OPS",
        "/ops/connectors/account/logout",
        f"provider_disconnected:{provider_id}",
        operation="WRITE",
        actor=_actor_label(auth),
    )
    return result
