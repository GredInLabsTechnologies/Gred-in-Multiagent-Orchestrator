"""Token mastery and cost analytics commands."""

from __future__ import annotations

import typer
from rich.table import Table

from gimo_cli import app, console
from gimo_cli.api import api_request
from gimo_cli.config import load_config
from gimo_cli.render import render_response, FORECAST, ANALYTICS
from gimo_cli.stream import emit_output

mastery_app = typer.Typer(name="mastery", help="Token economy, cost analytics, and budget forecast.")
app.add_typer(mastery_app, name="mastery")


@mastery_app.command("status")
def mastery_status(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show token mastery status (economy, hardware, efficiency)."""
    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/mastery/status")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        table = Table(title="Token Mastery", show_header=False)
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="magenta")
        for k, v in payload.items():
            if not isinstance(v, (dict, list)):
                table.add_row(k, str(v))
        console.print(table)
    else:
        console.print(f"[dim]{payload}[/dim]")


@mastery_app.command("forecast")
def mastery_forecast(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show budget forecast and burn rate."""
    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/mastery/forecast")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    render_response(payload, FORECAST, json_output=json_output)


@mastery_app.command("analytics")
def mastery_analytics(
    days: int = typer.Option(30, "--days", help="Number of days for analytics."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show cost analytics over a time range."""
    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/mastery/analytics", params={"days": days})
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    render_response(payload, ANALYTICS, json_output=json_output)
