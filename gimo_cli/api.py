"""API request layer — server communication, capabilities, token resolution."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from gimo_cli import console
from gimo_cli.bond import load_bond, resolve_bond_token
from gimo_cli.config import (
    DEFAULT_API_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    YAML_AVAILABLE,
    yaml,
    load_config,
    project_root,
    read_token_from_env_file,
)

# ── Capabilities cache ────────────────────────────────────────────────────────

_caps_cache: dict[str, Any] = {}
_caps_ts: float = 0.0
_CAPS_TTL = 300.0


def resolve_server_url(config: dict[str, Any]) -> str:
    env_url = os.environ.get("GIMO_API_URL") or os.environ.get("ORCH_API_URL")
    if env_url:
        return env_url.rstrip("/")
    api_cfg = config.get("api", {})
    if isinstance(api_cfg, dict):
        config_url = api_cfg.get("base_url")
        if config_url:
            return str(config_url).rstrip("/")
    return DEFAULT_API_BASE_URL.rstrip("/")


def resolve_token(role: str = "operator", config: dict[str, Any] | None = None) -> str | None:
    # 1. CLI Bond (Identity-First Auth) — highest priority for operator role
    if role == "operator":
        bond_jwt, bond_hint = resolve_bond_token()
        if bond_jwt:
            return bond_jwt
        if bond_hint:
            console.print(f"[yellow]{bond_hint}[/yellow]")

    # 2. Environment variables
    env_vars = {
        "admin": ["GIMO_TOKEN", "ORCH_TOKEN"],
        "operator": ["ORCH_OPERATOR_TOKEN"],
        "actions": ["ORCH_ACTIONS_TOKEN"],
    }

    for env_name in env_vars.get(role, []):
        token = os.environ.get(env_name)
        if token:
            return token.strip()

    # 3. Legacy ServerBond (YAML-based)
    if config is None:
        config = load_config()
    server_url = resolve_server_url(config)
    bond = load_bond(server_url)
    if bond and bond.get("role") == role:
        token = bond.get("token")
        if token:
            return str(token).strip()

    # 4. Inline config token
    api_cfg = config.get("api", {})
    if isinstance(api_cfg, dict):
        inline_token = api_cfg.get("token")
        if inline_token:
            return str(inline_token).strip()

    # 5. Server credential files (local dev)
    pr = project_root()
    server_dir = pr / "tools" / "gimo_server"
    if server_dir.exists() and server_dir.is_dir():
        unified_creds = server_dir / ".gimo_credentials"
        if unified_creds.exists() and YAML_AVAILABLE and yaml:
            try:
                creds = yaml.safe_load(unified_creds.read_text(encoding="utf-8"))
                if isinstance(creds, dict) and role in creds:
                    token = str(creds[role]).strip()
                    if token:
                        return token
            except Exception:
                pass

        legacy_files = {
            "admin": ".orch_token",
            "operator": ".orch_operator_token",
            "actions": ".orch_actions_token",
        }
        if role in legacy_files:
            token_path = server_dir / legacy_files[role]
            if token_path.exists():
                return token_path.read_text(encoding="utf-8").strip()

        if role == "admin":
            return read_token_from_env_file()

    return None


def fetch_capabilities(config: dict[str, Any]) -> dict[str, Any]:
    global _caps_cache, _caps_ts
    if _caps_cache and (time.time() - _caps_ts) < _CAPS_TTL:
        return _caps_cache
    try:
        base_url = resolve_server_url(config)
        token = resolve_token("operator", config)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{base_url}/ops/capabilities", headers=headers)
            if resp.status_code == 200:
                _caps_cache = resp.json()
                _caps_ts = time.time()
                return _caps_cache
    except Exception:
        pass
    return {}


def smart_timeout(path: str, config: dict[str, Any]) -> float | None:
    caps = fetch_capabilities(config)
    hints = caps.get("hints", {})
    # Server-driven operation timeouts (authoritative)
    op_timeouts = hints.get("operation_timeouts", {})
    for pattern, timeout_val in op_timeouts.items():
        if pattern in path:
            return None if timeout_val == 0 else float(timeout_val)
    # Fallback for paths not covered by operation_timeouts
    if any(p in path for p in ("/generate-plan", "/slice0", "/threads/", "/mastery/analytics")):
        return float(hints.get("generation_timeout_s", 180))
    if "/stream" in path or "/events" in path:
        return None
    if "/chat" in path:
        return float(hints.get("generation_timeout_s", 180))
    # Runs polling can be slow under load — use generation timeout
    if "/runs/" in path:
        return float(hints.get("generation_timeout_s", 180))
    return float(hints.get("default_timeout_s", 30))


def api_settings(config: dict[str, Any]) -> tuple[str, float]:
    api_cfg = dict(config.get("api") or {})
    base_url = str(api_cfg.get("base_url") or DEFAULT_API_BASE_URL).rstrip("/")
    timeout_seconds = float(api_cfg.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    return base_url, timeout_seconds


def _try_auto_start(base_url: str) -> bool:
    """Offer to auto-start the server when unreachable. Returns True if started."""
    # Don't auto-start if GIMO_NO_AUTOSTART is set (CI, scripts, etc.)
    if os.environ.get("GIMO_NO_AUTOSTART", "").lower() in ("1", "true", "yes"):
        return False

    # Don't auto-start for remote servers
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        return False

    # Extract port from URL
    port = parsed.port or 9325

    try:
        import sys
        if not sys.stdin.isatty():
            return False
    except Exception:
        return False

    console.print(f"[yellow]Server not reachable at {base_url}[/yellow]")
    try:
        answer = input("Start server? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if answer in ("", "y", "yes", "si", "sí"):
        console.print("[dim]Starting GIMO server...[/dim]")
        from gimo_cli.commands.server import start_server
        if start_server(host=parsed.hostname or "127.0.0.1", port=port):
            console.print("[green][OK] Server auto-started[/green]")
            return True
        else:
            console.print("[red][X] Auto-start failed[/red]")
            return False

    return False


def api_request(
    config: dict[str, Any],
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    role: str = "operator",
) -> tuple[int, Any]:
    base_url, config_timeout = api_settings(config)
    token = resolve_token(role, config)
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    timeout_seconds = smart_timeout(path, config) if config_timeout == DEFAULT_TIMEOUT_SECONDS else config_timeout

    orch_cfg = config.get("orchestrator") or {}
    preferred_model = orch_cfg.get("preferred_model")
    if preferred_model:
        headers["X-Preferred-Model"] = str(preferred_model)

    if extra_headers:
        headers.update(extra_headers)

    # Inject workspace context so the server knows CLI's working directory.
    if "X-Gimo-Workspace" not in headers:
        headers["X-Gimo-Workspace"] = str(project_root())

    # Identify this surface as CLI for unified authority chain.
    if "X-GIMO-Surface" not in headers:
        headers["X-GIMO-Surface"] = "cli"

    url = f"{base_url}{path}"

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.request(method, url, params=params, json=json_body, headers=headers)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        # Auto-start: offer to launch the server interactively
        if _try_auto_start(base_url):
            # Retry the request after successful auto-start
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    response = client.request(method, url, params=params, json=json_body, headers=headers)
            except (httpx.ConnectError, httpx.TimeoutException) as retry_exc:
                console.print(f"[red]Server still unreachable after auto-start[/red]")
                console.print(f"[dim]  Error: {retry_exc}[/dim]")
                return 503, {"error": "server_unreachable", "detail": str(retry_exc)}
        else:
            console.print(f"[red]Server unreachable at {base_url}[/red]")
            console.print(f"[dim]  Error: {exc}[/dim]")
            console.print("[yellow]Start manually with: gimo up[/yellow]")
            return 503, {"error": "server_unreachable", "detail": str(exc)}

    payload: Any
    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    if response.status_code == 401:
        server_url = resolve_server_url(config)
        bond = load_bond(server_url)
        if bond:
            console.print("[yellow]ServerBond token expired or invalid[/yellow]")
            console.print(f"[cyan]Re-authenticate with: gimo login {server_url}[/cyan]")
        else:
            console.print("[yellow]Not authenticated[/yellow]")
            console.print(f"[cyan]Login first: gimo login {server_url}[/cyan]")

    return response.status_code, payload


def provider_config_request(config: dict[str, Any]) -> tuple[int, Any]:
    status_code, payload = api_request(config, "GET", "/ops/providers")
    if status_code != 404:
        return status_code, payload
    return api_request(config, "GET", "/ops/provider")


def chat_provider_summary(config: dict[str, Any]) -> tuple[str, str]:
    status_code, payload = api_request(config, "GET", "/ops/operator/status")
    if status_code != 200 or not isinstance(payload, dict):
        return "unknown", "unknown"
    provider_id = str(payload.get("active_provider") or "unknown")
    model_id = str(payload.get("active_model") or "unknown")
    return provider_id, model_id


def select_chat_provider(
    config: dict[str, Any],
    provider_id: str,
    *,
    model: str | None = None,
    prefer_family: str | None = None,
) -> tuple[int, Any]:
    payload: dict[str, Any] = {"provider_id": provider_id}
    if model:
        payload["model"] = model
    if prefer_family:
        payload["prefer_family"] = prefer_family
    return api_request(config, "POST", "/ops/provider/select", json_body=payload)
