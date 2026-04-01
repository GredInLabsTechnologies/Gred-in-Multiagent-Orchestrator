"""Run, merge, and watch commands."""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx
import typer
from rich.panel import Panel

from gimo_cli import app, console
from gimo_cli.api import api_request
from gimo_cli.config import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_WATCH_TIMEOUT_SECONDS,
    load_config,
    runs_dir,
)
from gimo_cli.stream import emit_output, poll_run, stream_events, write_json


@app.command()
def run(
    plan_id: str = typer.Argument(..., help="Draft id to approve and execute"),
    auto: bool = typer.Option(True, "--auto/--approve-only", help="Spawn the backend run immediately after approval."),
    confirm: bool = typer.Option(True, "--confirm/--no-confirm", help="Confirm before approval when interactive."),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Poll the run until it reaches a terminal status."),
    poll_interval: float = typer.Option(DEFAULT_POLL_INTERVAL_SECONDS, "--poll-interval", min=0.1, help="Polling interval in seconds."),
    timeout_seconds: float = typer.Option(300.0, "--timeout", min=1.0, help="Maximum wait time when polling."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Approve a draft and optionally start its backend run."""
    config = load_config()
    if confirm and sys.stdin.isatty():
        action = "approve and execute" if auto else "approve without execution"
        if not typer.confirm(f"Proceed to {action} draft {plan_id}?", default=True):
            console.print("[yellow]Run aborted by user.[/yellow]")
            raise typer.Exit(1)

    query = {"auto_run": "true" if auto else "false"}

    with console.status("[bold green]Approving draft..."):
        status_code, payload = api_request(config, "POST", f"/ops/drafts/{plan_id}/approve", params=query)

    if status_code != 200 or not isinstance(payload, dict):
        console.print(f"[red]Run start failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)

    approved = payload.get("approved") if isinstance(payload.get("approved"), dict) else {}
    run_payload = payload.get("run") if isinstance(payload.get("run"), dict) else None

    record_id = str(run_payload.get("id", "")) if run_payload else ""
    if not record_id:
        import uuid
        record_id = f"{plan_id}_{uuid.uuid4().hex[:8]}"

    run_path = runs_dir() / f"{record_id}.json"
    write_json(run_path, payload)

    final_run_payload = run_payload
    if auto and wait and isinstance(run_payload, dict) and run_payload.get("id"):
        final_run_payload = poll_run(
            config,
            str(run_payload["id"]),
            poll_interval_seconds=poll_interval,
            timeout_seconds=timeout_seconds,
            announce=not json_output,
        )
        payload["run"] = final_run_payload
        write_json(run_path, payload)

    if json_output:
        emit_output(payload, json_output=True)
        return

    if final_run_payload:
        console.print(
            Panel(
                "\n".join([
                    "[bold green]Run started.[/bold green]",
                    f"Draft ID: [bold]{plan_id}[/bold]",
                    f"Approved ID: {approved.get('id', 'unknown')}",
                    f"Run ID: [bold]{final_run_payload.get('id', 'unknown')}[/bold]",
                    f"Status: {final_run_payload.get('status', 'unknown')}",
                    f"Stage: {final_run_payload.get('stage', 'n/a')}",
                ]),
                title="GIMO Run",
                border_style="blue",
            )
        )


@app.command()
def merge(
    run_id: str = typer.Argument(..., help="Run ID in AWAITING_MERGE status to finalize."),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Poll the run until it reaches a terminal status."),
    poll_interval: float = typer.Option(DEFAULT_POLL_INTERVAL_SECONDS, "--poll-interval", min=0.1, help="Polling interval in seconds."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Perform authoritative manual merge for a run that passed dry-run gates."""
    config = load_config()

    with console.status(f"[bold green]Triggering manual merge for {run_id}..."):
        status_code, payload = api_request(config, "POST", f"/ops/runs/{run_id}/merge")

    if status_code != 200:
        message = payload if isinstance(payload, str) else payload.get("detail", str(payload))
        console.print(f"[red]Merge failed ({status_code}): {message}[/red]")
        raise typer.Exit(1)

    final_run = payload
    if wait:
        final_run = poll_run(config, run_id, poll_interval_seconds=poll_interval, announce=not json_output)

    if json_output:
        emit_output(final_run, json_output=True)
        return

    run_status = final_run.get("status", "unknown")
    color = "green" if run_status == "done" else "red"
    console.print(
        Panel(
            f"Run ID: [bold]{run_id}[/bold]\nStatus: [{color}]{run_status}[/bold]\nMessage: {final_run.get('message', 'n/a')}",
            title="GIMO Manual Merge",
            border_style=color,
        )
    )


@app.command()
def watch(
    limit: int = typer.Option(10, "--limit", min=1, help="Maximum number of events to consume before exiting."),
    timeout_seconds: float = typer.Option(DEFAULT_WATCH_TIMEOUT_SECONDS, "--timeout", min=1.0, help="Read timeout for the event stream."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Watch the backend SSE stream for live orchestration events."""
    config = load_config()
    events: list[Any] = []

    try:
        for event in stream_events(config, timeout_seconds=timeout_seconds):
            events.append(event)
            if not json_output:
                if isinstance(event, dict):
                    event_type = str(event.get("event") or event.get("type") or "event")
                    console.print(f"[cyan]{event_type}[/cyan] {json.dumps(event, ensure_ascii=False)}")
                else:
                    console.print(str(event))
            if len(events) >= limit:
                break
    except httpx.HTTPError as exc:
        console.print(f"[red]Watch failed:[/red] {exc}")
        raise typer.Exit(1)

    if json_output:
        emit_output(events, json_output=True)
