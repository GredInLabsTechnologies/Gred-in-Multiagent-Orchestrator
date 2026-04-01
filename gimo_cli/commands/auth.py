"""Authentication commands: login, logout, doctor."""

from __future__ import annotations

import os
import subprocess
import time

import httpx
import typer
from rich.panel import Panel

from gimo_cli import app, console
from gimo_cli.api import api_request, resolve_server_url
from gimo_cli.bond import delete_bond, load_bond, save_bond
from gimo_cli.config import (
    DEFAULT_API_BASE_URL,
    YAML_AVAILABLE,
    yaml,
    load_config,
    project_root,
)


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

    if license_key:
        console.print("[yellow]License key auth not yet implemented (P2). Use token auth for now.[/yellow]")
        raise typer.Exit(1)

    if web:
        console.print("[yellow]Web OAuth not yet implemented (P2). Use token auth for now.[/yellow]")
        raise typer.Exit(1)

    console.print(f"[bold]Bonding to GIMO server:[/bold] {normalized_url}")

    token = os.getenv("ORCH_OPERATOR_TOKEN", "").strip()
    if token:
        console.print("[dim]Using token from ORCH_OPERATOR_TOKEN environment variable[/dim]")
    else:
        console.print("[dim]Enter server token (from server's .gimo_credentials or ORCH_OPERATOR_TOKEN):[/dim]")
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

    bond_path = save_bond(
        server_url=normalized_url,
        token=token,
        role=role,
        capabilities=features,
        plan=plan_type,
        auth_method="token",
        server_version=version,
    )

    console.print(f"[green][OK] Bonded to GIMO v{version} as {role}[/green]")
    console.print(f"[dim]Bond saved: {bond_path}[/dim]")
    console.print(f"[cyan]Plan: {plan_type} | Features: {', '.join(features)}[/cyan]")
    console.print(f"\n[bold]Next steps:[/bold]")
    console.print(f"  \u2022 Check bond health: [cyan]gimo doctor[/cyan]")
    console.print(f"  \u2022 View server status: [cyan]gimo status[/cyan]")


@app.command()
def logout(
    server_url: str = typer.Argument("", help="Server URL to disconnect from (default: current config)."),
) -> None:
    """Remove ServerBond for a given server."""
    config = load_config(require_project=False)
    target_url = server_url.rstrip("/") if server_url else resolve_server_url(config)

    deleted = delete_bond(target_url)
    if deleted:
        console.print(f"[green][OK] Disconnected from {target_url}[/green]")
        console.print(f"[dim]Bond removed from ~/.gimo/bonds/[/dim]")
    else:
        console.print(f"[yellow][!] No bond found for {target_url}[/yellow]")


@app.command()
def doctor() -> None:
    """Comprehensive health check with actionable hints."""
    config = load_config(require_project=False)
    server_url = resolve_server_url(config)
    console.print(f"[bold]GIMO Doctor Report[/bold]\n")

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
        console.print(f"[yellow][>] Start the server or check URL in .gimo/config.yaml[/yellow]")

    bond = load_bond(server_url)
    if bond:
        bonded_at = bond.get("bonded_at", "unknown")
        role = bond.get("role", "unknown")
        plan_type = bond.get("plan", "unknown")
        console.print(f"[green][OK] Bond:[/green] valid ({role}, plan: {plan_type}, bonded: {bonded_at[:19]})")
    else:
        console.print(f"[red][X] Bond:[/red] not found")
        console.print(f"[yellow][>] Run: gimo login {server_url}[/yellow]")

    cfg_path = project_root() / ".gimo" / "config.yaml"
    if cfg_path.exists():
        console.print(f"[green][OK] Config:[/green] .gimo/config.yaml found")
    else:
        console.print(f"[yellow][!] Config:[/yellow] .gimo/config.yaml missing")
        console.print(f"[yellow][>] Run: gimo init[/yellow]")

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

    if bond:
        try:
            token = bond.get("token", "")
            with httpx.Client(timeout=5.0) as client:
                prov_resp = client.get(
                    f"{server_url}/ops/provider",
                    headers={"Authorization": f"Bearer {token}"}
                )
                if prov_resp.status_code == 200:
                    prov_data = prov_resp.json()
                    active = prov_data.get("active") or prov_data.get("orchestrator_provider", "unknown")
                    providers = prov_data.get("providers", {})

                    if not active or active == "none":
                        console.print(f"[red][X] Provider:[/red] not configured")
                        console.print(f"[yellow][>] Set provider: [cyan]gimo providers set <name>[/cyan][/yellow]")
                    elif active and active in providers:
                        ptype = providers[active].get("provider_type", "unknown")
                        model_id = prov_data.get("model_id", "default")
                        console.print(f"[green][OK] Provider:[/green] {active} ({ptype}, model: {model_id})")

                        try:
                            health_resp = client.get(
                                f"{server_url}/ops/connectors/{active}/health",
                                headers={"Authorization": f"Bearer {token}"},
                                timeout=8.0,
                            )
                            if health_resp.status_code == 200:
                                health_result = health_resp.json()
                                st = health_result.get("status", "unknown")
                                if st == "ok":
                                    console.print(f"[green][OK] Provider connectivity:[/green] healthy")
                                elif st == "degraded":
                                    console.print(f"[yellow][!] Provider connectivity:[/yellow] degraded")
                                else:
                                    console.print(f"[yellow][!] Provider connectivity:[/yellow] {st}")
                            else:
                                console.print(f"[yellow][!] Provider connectivity:[/yellow] test failed ({health_resp.status_code})")
                        except httpx.TimeoutException:
                            console.print(f"[yellow][!] Provider connectivity:[/yellow] timeout (slow network or provider down)")
                        except Exception as health_exc:
                            console.print(f"[yellow][!] Provider connectivity:[/yellow] {str(health_exc)[:60]}")
                    else:
                        console.print(f"[yellow][!] Provider:[/yellow] active '{active}' not in providers list")
                        console.print(f"[yellow][>] Check: [cyan]gimo providers list[/cyan][/yellow]")
                else:
                    console.print(f"[yellow][!] Provider:[/yellow] could not fetch ({prov_resp.status_code})")
        except Exception as exc:
            console.print(f"[yellow][!] Provider:[/yellow] check failed: {str(exc)[:60]}")

    console.print(f"\n[dim]Run 'gimo --help' for available commands[/dim]")
