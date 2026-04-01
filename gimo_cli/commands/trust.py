"""Trust engine commands."""

from __future__ import annotations

import sys

import typer
from rich.table import Table

from gimo_cli import app, console
from gimo_cli.api import api_request
from gimo_cli.config import load_config
from gimo_cli.stream import emit_output

trust_app = typer.Typer(name="trust", help="Trust engine dashboard and controls.")
app.add_typer(trust_app, name="trust")


@trust_app.command("status")
def trust_status(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show trust engine dashboard."""
    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/trust/dashboard")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        table = Table(title="Trust Dashboard", show_header=True)
        table.add_column("Dimension", style="cyan")
        table.add_column("Score", style="magenta")
        table.add_column("State", style="white")
        entries = payload.get("entries") or payload.get("dimensions") or []
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    table.add_row(
                        str(entry.get("dimension", entry.get("key", "?"))),
                        str(entry.get("score", "?")),
                        str(entry.get("state", entry.get("circuit_state", "?"))),
                    )
        console.print(table)
        summary = payload.get("summary") or payload.get("aggregate")
        if summary:
            console.print(f"[dim]Aggregate: {summary}[/dim]")
    else:
        console.print(payload)


@trust_app.command("reset")
def trust_reset(
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Reset trust engine state."""
    if not yes and sys.stdin.isatty():
        if not typer.confirm("Reset trust engine? This clears all trust scores.", default=False):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)
    config = load_config()
    status_code, payload = api_request(config, "POST", "/ops/trust/reset")
    if json_output:
        emit_output({"status_code": status_code, "result": payload}, json_output=True)
        return
    if status_code == 200:
        console.print("[green]Trust engine reset successfully.[/green]")
    else:
        console.print(f"[red]Reset failed ({status_code}): {payload}[/red]")
