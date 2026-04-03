"""Provider management commands."""

from __future__ import annotations

import time

import typer
from rich.table import Table

from gimo_cli import app, console
from gimo_cli.api import api_request, provider_config_request
from gimo_cli.config import load_config
from gimo_cli.stream import emit_output

providers_app = typer.Typer(name="providers", help="Manage LLM providers and connectors.")
app.add_typer(providers_app, name="providers")


@providers_app.command("list")
def providers_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List configured providers."""
    config = load_config()
    status_code, payload = provider_config_request(config)
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return

    if not isinstance(payload, dict):
        console.print(f"[dim]{payload}[/dim]")
        return

    active = payload.get("active", "none")
    model_id = payload.get("model_id", "default")
    provider_type = payload.get("provider_type", "unknown")
    providers = payload.get("providers", {})

    console.print("[bold]Active Provider:[/bold]", style="cyan")
    if active and active != "none":
        console.print(f"  {active} ({provider_type})", style="green")
        console.print(f"  Model: {model_id}", style="dim")
    else:
        console.print("  [red]None configured[/red]")
        console.print("  [yellow]-> Set provider:[/yellow] [cyan]gimo providers set <name>[/cyan]")

    if providers:
        console.print("\n[bold]Available Providers:[/bold]", style="cyan")
        for pid, pdata in providers.items():
            if isinstance(pdata, dict):
                ptype = pdata.get("provider_type") or pdata.get("type", "unknown")
                is_active = pid == active
                marker = "[green]*[/green]" if is_active else " "
                console.print(f"  {marker} {pid} ({ptype})")
            else:
                console.print(f"    {pid}: {pdata}")

    roles = payload.get("roles", {})
    if roles:
        console.print("\n[bold]Roles:[/bold]", style="cyan")
        orch_prov = roles.get("orchestrator", {}).get("provider_id", "none")
        orch_model = roles.get("orchestrator", {}).get("model", "default")
        console.print(f"  Orchestrator: {orch_prov} / {orch_model}")
        workers = roles.get("workers", [])
        if workers:
            for w in workers:
                wprov = w.get("provider_id", "?")
                wmodel = w.get("model", "?")
                console.print(f"  Worker: {wprov} / {wmodel}")

    console.print("\n[dim]Commands:[/dim]")
    console.print("  [cyan]gimo providers set <name>[/cyan]     - Set active provider")
    console.print("  [cyan]gimo providers test <name>[/cyan]    - Test connectivity")
    console.print("  [cyan]gimo doctor[/cyan]                   - Health check")


@providers_app.command("set")
def providers_set(
    provider_id: str = typer.Argument(..., help="Provider ID to activate (e.g., openai, claude-account, ollama_local)."),
    model: str = typer.Option(None, "--model", "-m", help="Optional model to use with this provider."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Set active provider for orchestrator.

    Examples:
        gimo providers set openai
        gimo providers set claude-account --model claude-sonnet-4-5
        gimo providers set ollama_local --model llama3
    """
    config = load_config()

    payload_data = {"provider_id": provider_id}
    if model:
        payload_data["model"] = model

    with console.status(f"[bold green]Setting provider to {provider_id}..."):
        status_code, payload = api_request(
            config, "POST", "/ops/provider/select",
            json_body=payload_data, role="admin",
        )

    if status_code != 200:
        error_msg = payload if isinstance(payload, str) else payload.get("detail", str(payload))
        console.print(f"[red][X] Failed to set provider ({status_code}): {error_msg}[/red]")
        console.print("[yellow]-> Check available providers: [cyan]gimo providers list[/cyan][/yellow]")
        raise typer.Exit(1)

    if json_output:
        emit_output(payload, json_output=True)
        return

    active = payload.get("active", provider_id) if isinstance(payload, dict) else provider_id
    model_id = payload.get("model_id", model) if isinstance(payload, dict) else model
    console.print(f"[green][OK] Active provider set to: {active}[/green]")
    if model_id:
        console.print(f"[cyan]Model: {model_id}[/cyan]")
    console.print("\n[dim]Verify with:[/dim] [cyan]gimo providers list[/cyan]")


@providers_app.command("activate")
def providers_activate(
    provider_id: str = typer.Argument(..., help="Provider ID to activate."),
    model: str = typer.Option(None, "--model", "-m", help="Optional model to use."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Alias for 'gimo providers set' (user-friendly)."""
    providers_set(provider_id, model, json_output)


@providers_app.command("test")
def providers_test(
    provider_id: str = typer.Argument(..., help="Provider ID to test."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Test connectivity for a provider."""
    config = load_config()
    status_code, payload = api_request(config, "GET", f"/ops/connectors/{provider_id}/health")
    if json_output:
        emit_output({"status_code": status_code, "result": payload}, json_output=True)
        return
    if status_code == 200:
        console.print(f"[green]Provider '{provider_id}' is healthy.[/green]")
    else:
        console.print(f"[red]Provider '{provider_id}' test failed ({status_code}): {payload}[/red]")


@providers_app.command("models")
def providers_models(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List models available from the active provider."""
    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/provider/models")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    if isinstance(payload, list):
        table = Table(title="Available Models", show_header=True)
        table.add_column("Model", style="cyan")
        for m in payload:
            name = m.get("id", str(m)) if isinstance(m, dict) else str(m)
            table.add_row(name)
        console.print(table)
    else:
        console.print_json(data=payload) if isinstance(payload, (dict, list)) else console.print(f"[dim]{payload}[/dim]")


@providers_app.command("login")
def providers_login(
    provider_id: str = typer.Argument("", help="Provider to authenticate (codex/claude). Auto-detects active if omitted."),
) -> None:
    """Authenticate with an LLM provider via device flow.

    Supports: codex, claude

    Example:
      gimo providers login codex
    """
    config = load_config()

    if not provider_id:
        _, payload = api_request(config, "GET", "/ops/provider")
        if isinstance(payload, dict):
            provider_id = payload.get("active", "codex")
        else:
            provider_id = "codex"
        console.print(f"[dim]Auto-detected provider: {provider_id}[/dim]")

    provider_id = provider_id.lower().strip()

    console.print(f"[bold]Authenticating with {provider_id}...[/bold]")
    status_code, data = api_request(config, "POST", f"/ops/connectors/{provider_id}/login")

    if status_code >= 400:
        message = data.get("detail") if isinstance(data, dict) else str(data)
        console.print(f"[red]Login failed ({status_code}): {message}[/red]")
        raise typer.Exit(1)

    if isinstance(data, dict):
        url = data.get("verification_url") or data.get("url", "")
        code = data.get("user_code", "")
        poll_id = data.get("poll_id")

        if url and code:
            console.print(f"\n[bold cyan]Open this URL:[/bold cyan] {url}")
            console.print(f"[bold cyan]Enter code:[/bold cyan] {code}\n")
            console.print("[dim]Waiting for authorization... (complete in your browser)[/dim]")

            if poll_id:
                max_attempts = 60
                for attempt in range(max_attempts):
                    time.sleep(2)
                    poll_status, poll_data = api_request(config, "GET", f"/ops/connectors/account/login/{poll_id}")
                    if poll_status == 200 and isinstance(poll_data, dict):
                        state = poll_data.get("state", "pending")
                        if state == "completed":
                            console.print(f"[green][OK] {provider_id} authenticated successfully[/green]")
                            return
                        elif state == "failed":
                            error = poll_data.get("error", "unknown")
                            console.print(f"[red][X] Authentication failed: {error}[/red]")
                            raise typer.Exit(1)
                console.print(f"[yellow][!] Polling timeout. Check status with: gimo providers auth-status[/yellow]")
            else:
                console.print(f"[yellow][!] Complete auth in browser, then run: gimo providers auth-status[/yellow]")
        else:
            console.print(f"[yellow]Response: {data}[/yellow]")
    else:
        console.print(f"[yellow]Response: {data}[/yellow]")


@providers_app.command("auth-status")
def providers_auth_status() -> None:
    """Show authentication status for all CLI-based providers."""
    config = load_config(require_project=False)

    providers_to_check = ["codex", "claude"]
    table = Table(title="Provider Authentication Status", show_header=True)
    table.add_column("Provider", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Method", style="dim")

    for provider in providers_to_check:
        status_code, data = api_request(config, "GET", f"/ops/connectors/{provider}/auth-status")
        if status_code == 200 and isinstance(data, dict):
            authenticated = data.get("authenticated", False)
            method = data.get("method", "n/a")
            status_icon = "[OK]" if authenticated else "[X]"
            status_text = "authenticated" if authenticated else "not connected"
            table.add_row(provider, f"{status_icon} {status_text}", method)
        else:
            table.add_row(provider, "[X] error", f"HTTP {status_code}")

    console.print(table)


@providers_app.command("logout")
def providers_logout(
    provider_id: str = typer.Argument(..., help="Provider to disconnect (codex/claude)."),
) -> None:
    """Disconnect from an LLM provider.

    Example:
      gimo providers logout codex
    """
    config = load_config()
    provider_id = provider_id.lower().strip()

    status_code, data = api_request(config, "POST", f"/ops/connectors/{provider_id}/logout")

    if status_code < 300:
        console.print(f"[green][OK] {provider_id} disconnected[/green]")
    else:
        message = data.get("detail") if isinstance(data, dict) else str(data)
        console.print(f"[red]Logout failed ({status_code}): {message}[/red]")
        raise typer.Exit(1)
