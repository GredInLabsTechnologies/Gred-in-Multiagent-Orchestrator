"""Plan command."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import typer
from rich.panel import Panel

from gimo_cli import app, console
from gimo_cli.api import api_settings, provider_config_request, resolve_server_url, resolve_token
from gimo_cli.bond import load_bond, load_cli_bond
from gimo_cli.config import load_config, plans_dir
from gimo_cli.stream import emit_output, write_json


@app.command()
def plan(
    description: str = typer.Argument(..., help="Goal or task description"),
    workspace: str = typer.Option(None, "--workspace", "-w", help="Target workspace directory"),
    confirm: bool = typer.Option(True, "--confirm/--no-confirm", help="Confirm local persistence when interactive."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Create a structured draft plan and persist it under .gimo/plans."""
    config = load_config()
    ws_path = Path(workspace or ".").resolve()

    if not sys.stdin.isatty():
        confirm = False

    if confirm:
        console.print(f"[yellow]Workspace:[/yellow] {ws_path}")
        if not typer.confirm("Proceed?", default=True):
            raise typer.Exit(0)

    bond = load_cli_bond() or load_bond(resolve_server_url(config))
    if not bond:
        console.print("[red][X] No authentication found (CLI Bond or ServerBond)[/red]")
        console.print("[yellow]-> Run:[/yellow] [cyan]gimo login --web[/cyan] (recommended)")
        console.print("[yellow]-> Or:[/yellow]  [cyan]gimo login http://127.0.0.1:9325[/cyan]")
        raise typer.Exit(1)

    _, provider_cfg = provider_config_request(config)
    if isinstance(provider_cfg, dict):
        active_provider = provider_cfg.get("active")
        if not active_provider or active_provider == "none":
            console.print("[red][X] No active provider configured[/red]")
            console.print("[yellow]-> Check providers:[/yellow] [cyan]gimo providers list[/cyan]")
            console.print("[yellow]-> Set provider:[/yellow] [cyan]gimo providers set <name>[/cyan]")
            raise typer.Exit(1)

    base_url, connect_timeout = api_settings(config)
    token = resolve_token("operator", config)
    headers = {"Accept": "text/event-stream", "X-GIMO-Surface": "cli", "X-Gimo-Workspace": str(ws_path)}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{base_url}/ops/generate-plan-stream"
    timeout = httpx.Timeout(connect=connect_timeout, read=180.0, write=connect_timeout, pool=connect_timeout)

    payload = None
    with console.status("[bold green]Generating plan...") as status:
        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream("POST", url, params={"prompt": description}, headers=headers) as resp:
                    if resp.status_code != 200:
                        resp.read()
                        console.print(f"[red]Plan generation failed ({resp.status_code}): {resp.text}[/red]")
                        raise typer.Exit(1)
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if "result" in event:
                            payload = event["result"]
                        elif "error" in event:
                            console.print(f"[red]Plan generation failed: {event['error']}[/red]")
                            raise typer.Exit(1)
                        elif "stage" in event:
                            msg = event.get("message") or event["stage"]
                            pct = event.get("progress", "")
                            pct_str = f" ({int(float(pct)*100)}%)" if pct else ""
                            status.update(f"[bold green]{msg}{pct_str}[/bold green]")
        except httpx.ReadTimeout:
            console.print("[red]Plan generation timed out (180s).[/red]")
            raise typer.Exit(1)
        except httpx.HTTPError as exc:
            console.print(f"[red]Connection error: {exc}[/red]")
            raise typer.Exit(1)

    if not isinstance(payload, dict):
        console.print("[red]Plan generation failed: no draft received.[/red]")
        raise typer.Exit(1)

    draft_id = str(payload.get("draft_id") or payload.get("id") or "")
    if not draft_id:
        console.print("[red]Backend returned a draft without id.[/red]")
        raise typer.Exit(1)

    should_save = True
    if confirm and sys.stdin.isatty():
        preview = payload.get("content")
        if isinstance(preview, str) and preview.strip():
            console.print(Panel(preview[:800] + ("..." if len(preview) > 800 else ""), title="Plan Preview", border_style="cyan"))
        should_save = typer.confirm("Save this draft under .gimo/plans?", default=True)

    draft_path = plans_dir() / f"{draft_id}.json"
    if should_save:
        write_json(draft_path, payload)

    if json_output:
        emit_output(
            {"draft": payload, "saved_path": str(draft_path) if should_save else None, "saved": should_save},
            json_output=True,
        )
        return

    plan_status = payload.get("status", "draft")
    is_error = plan_status == "error"

    console.print(
        Panel(
            "\n".join([
                "[bold green]Plan generated successfully.[/bold green]" if not is_error else "[bold red]Plan generation failed.[/bold red]",
                f"Draft ID: [bold]{draft_id}[/bold]",
                f"Status: {plan_status}",
                f"Saved: {draft_path if should_save else 'not persisted locally'}",
            ]),
            title="GIMO Plan",
            border_style="green" if not is_error else "red",
        )
    )

    if is_error:
        error_detail = payload.get("error") or payload.get("error_detail") or "Unknown error"
        console.print(f"\n[red][X] Error:[/red] {error_detail}", style="bold")
        error_lower = str(error_detail).lower()
        if "bond" in error_lower or "auth" in error_lower or "token" in error_lower:
            console.print("[yellow]->[/yellow] Check authentication: [cyan]gimo doctor[/cyan]")
            console.print("[yellow]->[/yellow] Re-authenticate: [cyan]gimo login http://127.0.0.1:9325[/cyan]")
        elif "provider" in error_lower:
            console.print("[yellow]->[/yellow] Check providers: [cyan]gimo providers list[/cyan]")
            console.print("[yellow]->[/yellow] Configure provider in .gimo/config.yaml")
        raise typer.Exit(1)

    content = payload.get("content")
    if isinstance(content, str) and content.strip():
        preview = content[:600]
        if len(content) > 600:
            preview += "..."
        console.print(preview)
