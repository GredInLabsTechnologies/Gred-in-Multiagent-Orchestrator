"""Authentication commands: login, logout, doctor."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import httpx
import typer
from rich.panel import Panel

from gimo_cli import app, console
from gimo_cli.api import api_request, resolve_server_url, resolve_token
from gimo_cli.bond import (
    delete_bond,
    delete_cli_bond,
    load_bond,
    load_cli_bond,
    save_bond,
    save_cli_bond,
    verify_bond_jwt,
)
from gimo_cli.config import (
    DEFAULT_API_BASE_URL,
    YAML_AVAILABLE,
    yaml,
    load_config,
    project_root,
)


# ---------------------------------------------------------------------------
# OAuth callback server (for --web flow)
# ---------------------------------------------------------------------------

def _run_oauth_callback_server(timeout: int = 120) -> str | None:
    """Start a temporary HTTP server to receive the OAuth callback JWT.

    Returns the JWT string or None on timeout.
    """
    import http.server
    import threading
    import urllib.parse

    result: dict[str, str | None] = {"jwt": None}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            token = params.get("token", [None])[0]
            if token:
                result["jwt"] = token
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>GIMO CLI Bonded!</h2>"
                    b"<p>You can close this tab.</p></body></html>"
                )
            else:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Missing token parameter")

        def log_message(self, format, *args):
            pass  # Suppress HTTP logs

    try:
        server = http.server.HTTPServer(("127.0.0.1", 19325), CallbackHandler)
    except OSError as e:
        console.print(f"[red]Cannot start OAuth callback server on port 19325: {e}[/red]")
        console.print("[yellow]Close any process using port 19325 and try again[/yellow]")
        return None
    server.timeout = timeout

    def serve():
        server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    server.server_close()

    return result.get("jwt")


@app.command()
def login(
    server_url: str = typer.Argument(DEFAULT_API_BASE_URL, help="Server URL to bond with."),
    license_key: str = typer.Option("", "--license", help="License key for GIMO WEB validation."),
    web: bool = typer.Option(False, "--web", help="Use Firebase OAuth (opens browser)."),
) -> None:
    """Authenticate with a GIMO server and create a ServerBond."""
    if not YAML_AVAILABLE or not yaml:
        console.print("[red]PyYAML required. Install with: pip install PyYAML>=6.0.2[/red]")
        raise typer.Exit(1)

    normalized_url = server_url.rstrip("/")

    # ── Web OAuth flow (Identity-First Auth) ──────────────────────────
    if web:
        import webbrowser
        from gimo_cli.bond import _hw_fingerprint, machine_id

        web_base = os.environ.get("GIMO_WEB_URL", "https://gimo-web.vercel.app")
        mid = machine_id()
        fp = _hw_fingerprint()

        callback_url = "http://127.0.0.1:19325/callback"
        auth_url = (
            f"{web_base}/cli/auth"
            f"?callback={callback_url}"
            f"&machine_id={mid}"
            f"&fingerprint={fp[:16]}"
        )

        console.print("[bold]Opening GIMO Web for authentication...[/bold]")
        console.print(f"[dim]If browser doesn't open, visit: {auth_url}[/dim]\n")

        webbrowser.open(auth_url)
        console.print("[dim]Waiting for OAuth callback (2 min timeout)...[/dim]")

        jwt_token = _run_oauth_callback_server(timeout=120)
        if not jwt_token:
            console.print("[red][X] OAuth timeout — no callback received[/red]")
            console.print("[yellow]Try again with: gimo login --web[/yellow]")
            raise typer.Exit(1)

        # Verify the JWT before saving
        payload = verify_bond_jwt(jwt_token)
        if not payload:
            console.print("[red][X] Received invalid JWT from GIMO Web[/red]")
            raise typer.Exit(1)

        plan = payload.get("plan", "standard")
        uid = payload.get("uid", "unknown")

        delete_cli_bond()  # Clean any expired/stale bond before saving new one
        bond_path = save_cli_bond(jwt_token, metadata={
            "server_url": normalized_url,
            "uid": uid,
            "plan": plan,
        })

        console.print(f"[green][OK] Bonded as operator (plan: {plan})[/green]")
        console.print(f"[dim]Bond saved: {bond_path}[/dim]")
        console.print(f"[cyan]Offline-capable: yes | Machine-bound: yes[/cyan]")

        # Also create legacy bond for backwards compatibility
        try:
            with httpx.Client(timeout=10.0) as client:
                health_resp = client.get(f"{normalized_url}/health")
                if health_resp.status_code == 200:
                    health_data = health_resp.json()
                    version = health_data.get("version", "unknown")
                    save_bond(
                        server_url=normalized_url,
                        token=jwt_token,
                        role="operator",
                        capabilities=["plans", "runs", "chat"],
                        plan=plan,
                        auth_method="cli_bond",
                        server_version=version,
                    )
        except Exception:
            pass  # Legacy bond is optional

        return

    # ── License key flow (P2) ─────────────────────────────────────────
    if license_key:
        console.print("[yellow]License key auth not yet implemented (P2). Use --web or token auth.[/yellow]")
        raise typer.Exit(1)

    # ── Legacy token flow ─────────────────────────────────────────────
    console.print(f"[bold]Bonding to GIMO server:[/bold] {normalized_url}")

    token = os.getenv("ORCH_OPERATOR_TOKEN", "").strip()
    if token:
        console.print("[dim]Using token from ORCH_OPERATOR_TOKEN environment variable[/dim]")
    else:
        import sys
        if not sys.stdin.isatty():
            console.print("[red]Cannot prompt for token in non-interactive mode.[/red]")
            console.print("[cyan]Set ORCH_OPERATOR_TOKEN env var or run from a terminal.[/cyan]")
            raise typer.Exit(1)
        console.print("[dim]Enter server token (from .orch_token or ORCH_OPERATOR_TOKEN):[/dim]")
        import getpass
        token = getpass.getpass("Token: ").strip()
        if not token:
            console.print("[red]Token required[/red]")
            raise typer.Exit(1)

    console.print("[dim]Validating token...[/dim]")
    try:
        with httpx.Client(timeout=10.0) as client:
            health_resp = client.get(f"{normalized_url}/health")
            if health_resp.status_code != 200:
                console.print(f"[red]Server health check failed ({health_resp.status_code})[/red]")
                raise typer.Exit(1)

            caps_resp = client.get(
                f"{normalized_url}/ops/capabilities",
                headers={"Authorization": f"Bearer {token}"}
            )
            if caps_resp.status_code == 401:
                console.print("[red][X] Invalid token[/red]")
                raise typer.Exit(1)
            if caps_resp.status_code != 200:
                console.print(f"[yellow][!] Could not fetch capabilities ({caps_resp.status_code}), using defaults[/yellow]")
                capabilities_data = {
                    "version": "unknown",
                    "role": "operator",
                    "plan": "local",
                    "features": ["plans", "runs", "chat"],
                }
            else:
                capabilities_data = caps_resp.json()

    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        console.print(f"[red][X] Cannot reach server at {normalized_url}[/red]")
        console.print(f"[dim]  {exc}[/dim]")
        raise typer.Exit(1)

    role = capabilities_data.get("role", "operator")
    plan_type = capabilities_data.get("plan", "local")
    features = capabilities_data.get("features", [])
    version = capabilities_data.get("version", "unknown")

    delete_cli_bond()  # Clean any expired/stale CLI bond before saving legacy bond
    bond_path = save_bond(
        server_url=normalized_url,
        token=token,
        role=role,
        capabilities=features,
        plan=plan_type,
        auth_method="token",
        server_version=version,
    )

    # Also create CLI Bond (AES-256-GCM) so `gimo doctor` shows both bonds OK.
    # Only attempt for JWT tokens (3 dot-separated parts) — raw API tokens
    # are not valid JWTs and will fail verify_bond_jwt() later.
    if token.count(".") >= 2:
        try:
            save_cli_bond(token)
        except Exception:
            pass  # Non-fatal: legacy bond is sufficient for operation

    console.print(f"[green][OK] Bonded to GIMO v{version} as {role}[/green]")
    console.print(f"[dim]Bond saved: {bond_path}[/dim]")
    console.print(f"[cyan]Plan: {plan_type} | Features: {', '.join(features)}[/cyan]")
    console.print(f"\n[bold]Next steps:[/bold]")
    console.print(f"  \u2022 Check bond health: [cyan]gimo doctor[/cyan]")


@app.command()
def logout(
    server_url: str = typer.Argument("", help="Server URL to disconnect from (default: current config)."),
) -> None:
    """Remove ServerBond and CLI Bond for a given server."""
    config = load_config(require_project=False)
    target_url = server_url.rstrip("/") if server_url else resolve_server_url(config)

    # Delete CLI Bond (Identity-First Auth)
    cli_deleted = delete_cli_bond()

    # Delete legacy ServerBond
    legacy_deleted = delete_bond(target_url)

    if cli_deleted or legacy_deleted:
        console.print(f"[green][OK] Disconnected from {target_url}[/green]")
        if cli_deleted:
            console.print("[dim]CLI Bond removed from ~/.gimo/bond.enc[/dim]")
        if legacy_deleted:
            console.print("[dim]Legacy bond removed from ~/.gimo/bonds/[/dim]")
    else:
        console.print(f"[yellow][!] No bond found for {target_url}[/yellow]")


@app.command()
def doctor() -> None:
    """Comprehensive health check with actionable hints."""
    config = load_config(require_project=False)
    server_url = resolve_server_url(config)
    console.print(f"[bold]GIMO Doctor Report[/bold]\n")

    # ── Server check ──────────────────────────────────────────────────
    try:
        with httpx.Client(timeout=5.0) as client:
            health_resp = client.get(f"{server_url}/health")
            if health_resp.status_code == 200:
                health_data = health_resp.json()
                version = health_data.get("version", "unknown")
                console.print(f"[green][OK] Server:[/green] reachable ({server_url} v{version})")
            else:
                console.print(f"[red][X] Server:[/red] HTTP {health_resp.status_code}")
    except Exception as exc:
        console.print(f"[red][X] Server:[/red] unreachable ({exc})")
        console.print(f"[yellow][>] Start the server: [cyan]gimo up[/cyan] or check URL in .gimo/config.yaml[/yellow]")

    # ── CLI Bond check (Identity-First Auth) ──────────────────────────
    cli_bond_missing = False
    cli_bond = load_cli_bond()
    if cli_bond:
        jwt_token = cli_bond.get("jwt", "")
        bonded_at = cli_bond.get("bonded_at", "unknown")
        payload = verify_bond_jwt(jwt_token) if jwt_token else None

        if payload:
            plan = payload.get("plan", "unknown")
            uid = payload.get("uid", "")
            exp = payload.get("exp", 0)
            days_left = max(0, int((exp - time.time()) / 86400)) if exp else 0
            console.print(
                f"[green][OK] CLI Bond:[/green] valid "
                f"(plan: {plan}, expires: {days_left}d, bonded: {bonded_at[:19]})"
            )
            console.print(f"[dim]     Machine-bound: yes | Offline-capable: yes | AES-256-GCM[/dim]")
        else:
            console.print(f"[red][X] CLI Bond:[/red] expired or invalid")
            console.print(f"[yellow][>] Renew with: [cyan]gimo login --web[/cyan][/yellow]")
    else:
        cli_bond_missing = True

    # ── Legacy bond check ─────────────────────────────────────────────
    bond = load_bond(server_url)
    if bond:
        bonded_at = bond.get("bonded_at", "unknown")
        role = bond.get("role", "unknown")
        plan_type = bond.get("plan", "unknown")
        auth_method = bond.get("auth_method", "token")
        console.print(
            f"[green][OK] Legacy Bond:[/green] valid "
            f"({role}, plan: {plan_type}, method: {auth_method}, bonded: {bonded_at[:19]})"
        )
    else:
        if not cli_bond:
            console.print(f"[red][X] Legacy Bond:[/red] not found")
            console.print(f"[yellow][>] Run: gimo login {server_url}[/yellow]")

    # Show CLI Bond hint only when no auth works at all
    if cli_bond_missing and not bond:
        console.print(f"[dim][~] CLI Bond:[/dim] not configured")
        console.print(f"[dim]     Upgrade: [cyan]gimo login --web[/cyan] for machine-bound auth[/dim]")

    # ── Config check ──────────────────────────────────────────────────
    cfg_path = project_root() / ".gimo" / "config.yaml"
    if cfg_path.exists():
        console.print(f"[green][OK] Config:[/green] .gimo/config.yaml found")
    else:
        console.print(f"[yellow][!] Config:[/yellow] .gimo/config.yaml missing")
        console.print(f"[yellow][>] Run: gimo init[/yellow]")

    # ── Git check ─────────────────────────────────────────────────────
    try:
        repo_root = project_root()
        git_dir = repo_root / ".git"
        if git_dir.exists():
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=repo_root, text=True, capture_output=True, check=False,
            )
            branch = branch_result.stdout.strip() or "detached"
            console.print(f"[green][OK] Git:[/green] repo detected ({repo_root.name}, branch: {branch})")
        else:
            console.print(f"[yellow][!] Git:[/yellow] no .git directory")
    except Exception:
        console.print(f"[yellow][!] Git:[/yellow] detection failed")

    # ── Provider check ────────────────────────────────────────────────
    # R17 Cluster E.2: doctor is now a thin client of the backend
    # /ops/providers/diagnostics endpoint. All probing logic lives server-side
    # in ProviderDiagnosticsService.
    active_bond = bond if bond else (cli_bond if cli_bond else None)
    if active_bond:
        try:
            cfg_for_call = load_config(require_project=False)
            status_code, payload = api_request(
                cfg_for_call, "GET", "/ops/providers/diagnostics", role="operator",
            )
            if status_code == 200 and isinstance(payload, dict):
                entries = payload.get("entries") or []
                total = payload.get("total", len(entries))
                healthy = payload.get("healthy", 0)
                if not entries:
                    console.print(f"[red][X] Provider:[/red] none configured")
                    console.print(f"[yellow][>] Set provider: [cyan]gimo providers set <name>[/cyan][/yellow]")
                else:
                    console.print(
                        f"[green][OK] Providers:[/green] {healthy}/{total} healthy"
                    )
                    for entry in entries:
                        pid = entry.get("provider_id", "?")
                        reach = entry.get("reachable")
                        auth_st = entry.get("auth_status", "missing")
                        if reach and auth_st == "ok":
                            console.print(f"   [green][OK][/green] {pid} (auth={auth_st})")
                        else:
                            tag = "[red][X][/red]" if not reach else "[yellow][!][/yellow]"
                            err = entry.get("error") or ""
                            extra = f" — {err}" if err else ""
                            console.print(
                                f"   {tag} {pid} (reachable={reach}, auth={auth_st}){extra}"
                            )
            else:
                console.print(f"[yellow][!] Provider:[/yellow] diagnostics fetch failed ({status_code})")
        except Exception as exc:
            console.print(f"[yellow][!] Provider:[/yellow] check failed: {str(exc)[:60]}")

    # ── HTTP probing hint (R19 Change 5) ──────────────────────────────
    # Operators occasionally need to hit /ops/* directly (curl, scripts).
    # The boundary stays fail-closed: no anonymous routes are opened.
    # We only confirm whether an operator token can be resolved from the
    # existing bootstrap chain and show how to probe safely WITHOUT
    # printing the secret on stdout.
    op_token = resolve_token("operator", config)
    console.print("\n[bold]HTTP probing[/bold]")
    if op_token:
        console.print("[green][OK] Operator token:[/green] resolvable from bootstrap (bond/env/config)")
        console.print("[dim]     Preferred (token never leaves CLI process):[/dim]")
        console.print(f"[cyan]       python -m gimo_cli status --json[/cyan]")
        console.print(f"[cyan]       python -m gimo_cli observe metrics[/cyan]")
        console.print(
            "[dim]     Direct HTTP: set ORCH_OPERATOR_TOKEN in your shell from your[/dim]"
        )
        console.print(
            "[dim]     bond/secret store, then call /ops/* with Authorization: Bearer.[/dim]"
        )
        console.print(
            f"[dim]     The /ops/* boundary stays fail-closed; no anonymous routes exist.[/dim]"
        )
    else:
        console.print("[yellow][!] Operator token:[/yellow] not resolvable from bootstrap chain")
        console.print(
            f"[yellow][>] Bond first: [cyan]gimo login --web[/cyan] or [cyan]gimo login {server_url}[/cyan][/yellow]"
        )

    console.print(f"\n[dim]Run 'gimo --help' for available commands[/dim]")
