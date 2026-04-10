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


def _resolve_existing_provider_id(config: dict, candidate: str) -> str:
    status_code, payload = api_request(config, "GET", "/ops/provider")
    if status_code != 200 or not isinstance(payload, dict):
        return candidate
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return candidate
    if candidate in providers:
        return candidate
    main_candidate = f"{candidate}-main"
    if main_candidate in providers:
        return main_candidate
    for pid, entry in providers.items():
        if not isinstance(entry, dict):
            continue
        entry_type = str(entry.get("provider_type") or entry.get("type") or "").strip().lower()
        if entry_type == candidate:
            return str(pid)
    return candidate


def _default_model_for_provider_type(provider_type: str) -> str:
    defaults = {
        "groq": "qwen/qwen3-32b",
        "cloudflare-workers-ai": "@cf/qwen/qwen2.5-coder-32b-instruct",
    }
    return defaults.get(provider_type, "gpt-4o-mini")


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
    api_key: str = typer.Option(None, "--api-key", help="API key for the provider (stored encrypted on server)."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Set active provider for orchestrator.

    Examples:
        gimo providers set openai --api-key sk-...
        gimo providers set claude-account --model claude-sonnet-4-5
        gimo providers set ollama_local --model llama3
    """
    config = load_config()

    payload_data = {"provider_id": provider_id}
    if model:
        payload_data["model"] = model
    if api_key:
        payload_data["api_key"] = api_key

    with console.status(f"[bold green]Setting provider to {provider_id}..."):
        status_code, payload = api_request(
            config, "POST", "/ops/provider/select",
            json_body=payload_data, role="operator",
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

    # Warn if provider has no credentials
    if not api_key:
        auth_code, auth_data = api_request(config, "GET", f"/ops/connectors/{provider_id}/auth-status")
        if auth_code == 200 and isinstance(auth_data, dict) and not auth_data.get("authenticated"):
            console.print(f"[yellow][!] Warning: {provider_id} is not authenticated. API calls will fail.[/yellow]")
            console.print(f"[yellow]    Run: [cyan]gimo providers login {provider_id} --api-key YOUR_KEY[/cyan][/yellow]")

    console.print("\n[dim]Verify with:[/dim] [cyan]gimo providers list[/cyan]")


@providers_app.command("activate")
def providers_activate(
    provider_id: str = typer.Argument(..., help="Provider ID to activate."),
    model: str = typer.Option(None, "--model", "-m", help="Optional model to use."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Alias for 'gimo providers set' (user-friendly)."""
    providers_set(provider_id, model, api_key=None, json_output=json_output)


@providers_app.command("add")
def providers_add(
    provider_id: str = typer.Argument(..., help="Provider ID to register without activating it."),
    provider_type: str = typer.Option(..., "--type", help="Canonical provider type, e.g. groq or cloudflare-workers-ai."),
    model: str = typer.Option(None, "--model", "-m", help="Default model for this provider entry."),
    base_url: str = typer.Option(None, "--base-url", help="Optional base URL override."),
    api_key: str = typer.Option(None, "--api-key", help="Optional API key to store encrypted on the server."),
    display_name: str = typer.Option(None, "--display-name", help="Optional display name."),
    activate: bool = typer.Option(False, "--activate", help="Also set this provider as active."),
) -> None:
    """Register or update a provider entry without changing the active provider by default."""
    config = load_config()
    canonical_type = provider_type.strip().lower()
    payload_data = {
        "provider_id": provider_id.strip(),
        "provider_type": canonical_type,
        "display_name": display_name,
        "base_url": base_url,
        "api_key": api_key,
        "model": model or _default_model_for_provider_type(canonical_type),
        "activate": activate,
    }

    with console.status(f"[bold green]Registering provider {provider_id}..."):
        status_code, payload = api_request(
            config, "POST", "/ops/provider/upsert",
            json_body=payload_data, role="admin",
        )

    if status_code != 200:
        error_msg = payload if isinstance(payload, str) else payload.get("detail", str(payload))
        console.print(f"[red][X] Failed to register provider ({status_code}): {error_msg}[/red]")
        raise typer.Exit(1)

    active = payload.get("active", "unknown") if isinstance(payload, dict) else "unknown"
    console.print(f"[green][OK] Provider '{provider_id}' registered[/green]")
    if activate:
        console.print(f"[cyan]Active provider: {active}[/cyan]")
    else:
        console.print(f"[dim]Active provider unchanged: {active}[/dim]")
    console.print("[dim]Verify with:[/dim] [cyan]gimo providers list[/cyan]")


@providers_app.command("test")
def providers_test(
    provider_id: str = typer.Argument(..., help="Provider ID to test."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Test connectivity for a provider.

    R17 Cluster E.2: thin client of /ops/providers/diagnostics — all probing
    logic lives in the backend ProviderDiagnosticsService so doctor and
    providers test see identical results.
    """
    config = load_config()
    status_code, payload = api_request(
        config, "GET", "/ops/providers/diagnostics", role="operator",
    )
    if json_output:
        # Filter to the requested provider when emitting JSON
        if status_code == 200 and isinstance(payload, dict):
            entries = [
                e for e in (payload.get("entries") or [])
                if e.get("provider_id") == provider_id
            ]
            emit_output(
                {"status_code": status_code, "result": entries[0] if entries else None},
                json_output=True,
            )
        else:
            emit_output({"status_code": status_code, "result": payload}, json_output=True)
        return

    if status_code != 200 or not isinstance(payload, dict):
        console.print(f"[red]Diagnostics fetch failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)

    entries = payload.get("entries") or []
    target = next((e for e in entries if e.get("provider_id") == provider_id), None)
    if target is None:
        console.print(f"[red]Provider '{provider_id}' not found in diagnostics report.[/red]")
        raise typer.Exit(1)

    reachable = target.get("reachable")
    auth_status = target.get("auth_status", "missing")
    method = target.get("method") or "n/a"
    error = target.get("error")

    if reachable:
        console.print(f"[green]Provider '{provider_id}' endpoint is reachable.[/green]")
    else:
        console.print(f"[red]Provider '{provider_id}' endpoint is unreachable.[/red]")
        if error:
            console.print(f"[red]  {error}[/red]")

    if auth_status == "ok":
        console.print(f"[green]Auth: authenticated ({method})[/green]")
    elif auth_status == "expired":
        console.print(f"[yellow]Auth: expired — run [cyan]gimo providers login {provider_id}[/cyan][/yellow]")
    elif auth_status == "error":
        console.print(f"[red]Auth: probe error[/red]")
    else:
        console.print(f"[yellow]Auth: not authenticated — run [cyan]gimo providers login {provider_id}[/cyan][/yellow]")


@providers_app.command("models")
def providers_models(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List models available from the active provider."""
    from gimo_cli.render import render_response, PROVIDER_MODELS

    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/provider/models")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    render_response(payload, PROVIDER_MODELS, json_output=json_output)


@providers_app.command("login")
def providers_login(
    provider_id: str = typer.Argument("", help="Provider to authenticate. Auto-detects active if omitted."),
    api_key: str = typer.Option(None, "--api-key", "-k", help="Authenticate with an API key instead of device flow."),
    base_url: str = typer.Option(None, "--base-url", help="Optional base URL to store alongside the credentials."),
) -> None:
    """Authenticate with an LLM provider.

    Supports two modes:
      1. Device flow (browser): gimo providers login claude
      2. API key:               gimo providers login claude --api-key sk-ant-...

    API key mode stores credentials without changing the active provider.

    Also reads from environment variables if --api-key is not provided:
      ANTHROPIC_API_KEY (for claude/anthropic providers)
      OPENAI_API_KEY   (for codex/openai providers)
      GROQ_API_KEY     (for groq providers)
      CLOUDFLARE_API_TOKEN (for cloudflare-workers-ai providers)

    Example:
      gimo providers login codex --api-key sk-...
      gimo providers login claude -k sk-ant-...
    """
    import os

    config = load_config()

    if not provider_id:
        _, payload = api_request(config, "GET", "/ops/provider")
        if isinstance(payload, dict):
            provider_id = payload.get("active", "codex")
        else:
            provider_id = "codex"
        console.print(f"[dim]Auto-detected provider: {provider_id}[/dim]")

    provider_id = provider_id.lower().strip()

    # --- API key mode: resolve from flag, env var, or prompt ---
    resolved_key = api_key
    if not resolved_key:
        env_map = {
            "claude": "ANTHROPIC_API_KEY",
            "claude-account": "ANTHROPIC_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "codex": "OPENAI_API_KEY",
            "codex-account": "OPENAI_API_KEY",
            "openai": "OPENAI_API_KEY",
            "groq": "GROQ_API_KEY",
            "groq-main": "GROQ_API_KEY",
            "cloudflare": "CLOUDFLARE_API_TOKEN",
            "workers-ai": "CLOUDFLARE_API_TOKEN",
            "cloudflare-workers-ai": "CLOUDFLARE_API_TOKEN",
            "cloudflare-workers-ai-main": "CLOUDFLARE_API_TOKEN",
        }
        env_var = env_map.get(provider_id)
        if env_var:
            resolved_key = os.environ.get(env_var)
            if resolved_key:
                console.print(f"[dim]Using API key from ${env_var}[/dim]")

    if resolved_key:
        # Resolve provider alias to actual config ID (e.g. claude → claude-account)
        alias_map = {
            "claude": "claude-account",
            "codex": "codex-account",
            "anthropic": "claude-account",
            "openai": "openai",
        }
        resolved_id = _resolve_existing_provider_id(config, alias_map.get(provider_id, provider_id))

        console.print(f"[bold]Storing API key for {resolved_id}...[/bold]")
        payload_data = {"api_key": resolved_key}
        if base_url:
            payload_data["base_url"] = base_url
        status_code, data = api_request(
            config, "POST", f"/ops/connectors/{resolved_id}/credentials",
            json_body=payload_data, role="operator",
        )
        if status_code == 200:
            active = data.get("active", "unknown") if isinstance(data, dict) else "unknown"
            console.print(f"[green][OK] API key stored for {resolved_id}[/green]")
            console.print(f"[dim]Active provider unchanged: {active}[/dim]")
            console.print(f"[dim]Activate later with:[/dim] [cyan]gimo providers set {resolved_id}[/cyan]")
            console.print(f"[dim]Verify with:[/dim] [cyan]gimo providers test {resolved_id}[/cyan]")
        else:
            error_msg = data.get("detail", str(data)) if isinstance(data, dict) else str(data)
            console.print(f"[red][X] Failed to authenticate ({status_code}): {error_msg}[/red]")
            console.print(f"[yellow]Tip: register it first with [cyan]gimo providers add {resolved_id} --type <provider-type>[/cyan][/yellow]")
            raise typer.Exit(1)
        return

    # --- Device flow mode (original behavior) ---
    console.print(f"[bold]Authenticating with {provider_id} via device flow...[/bold]")
    status_code, data = api_request(config, "POST", f"/ops/connectors/{provider_id}/login")

    if status_code >= 400:
        message = data.get("detail") if isinstance(data, dict) else str(data)
        console.print(f"[red]Login failed ({status_code}): {message}[/red]")
        console.print(f"[yellow]Tip: use [cyan]gimo providers login {provider_id} --api-key YOUR_KEY[/cyan] for API key auth[/yellow]")
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
