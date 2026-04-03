"""Observability commands: metrics, alerts, traces."""

from __future__ import annotations

import typer
from rich.table import Table

from gimo_cli import app, console
from gimo_cli.api import api_request
from gimo_cli.config import load_config
from gimo_cli.stream import emit_output

observe_app = typer.Typer(name="observe", help="Observability: metrics, traces, and alerts.")
app.add_typer(observe_app, name="observe")


@observe_app.command("metrics")
def observe_metrics(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show observability metrics."""
    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/observability/metrics")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        table = Table(title="Metrics", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="magenta")
        for k, v in payload.items():
            if not isinstance(v, (dict, list)):
                table.add_row(k, str(v))
        console.print(table)
    else:
        console.print_json(data=payload) if isinstance(payload, (dict, list)) else console.print(f"[dim]{payload}[/dim]")


@observe_app.command("alerts")
def observe_alerts(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show active alerts."""
    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/observability/alerts")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        alerts = payload.get("alerts", [])
        count = payload.get("count", len(alerts) if isinstance(alerts, list) else 0)
        if not alerts:
            console.print(f"[green]No active alerts. (count={count})[/green]")
            return
        table = Table(title="Alerts", show_header=True)
        table.add_column("Level", style="yellow")
        table.add_column("Message", style="white")
        for alert in (alerts if isinstance(alerts, list) else []):
            if isinstance(alert, dict):
                table.add_row(str(alert.get("level", "?")), str(alert.get("message", ""))[:80])
            else:
                table.add_row("?", str(alert)[:80])
        console.print(table)
    else:
        console.print_json(data=payload) if isinstance(payload, (dict, list)) else console.print(f"[dim]{payload}[/dim]")


@observe_app.command("traces")
def observe_traces(
    limit: int = typer.Option(10, "--limit", help="Number of traces."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show recent traces."""
    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/observability/traces", params={"limit": limit})
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    if isinstance(payload, list):
        table = Table(title="Traces", show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Duration", style="dim")
        for t in payload:
            if isinstance(t, dict):
                table.add_row(
                    str(t.get("trace_id", t.get("id", "?")))[:12],
                    str(t.get("status", "?")),
                    str(t.get("duration_ms", t.get("duration", "?")))[:10],
                )
        console.print(table)
    else:
        console.print_json(data=payload) if isinstance(payload, (dict, list)) else console.print(f"[dim]{payload}[/dim]")
