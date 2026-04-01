"""Conversation thread commands."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.table import Table

from gimo_cli import app, console
from gimo_cli.api import api_request
from gimo_cli.config import load_config
from gimo_cli.stream import emit_output

threads_app = typer.Typer(name="threads", help="Conversation thread management.")
app.add_typer(threads_app, name="threads")


@threads_app.command("list")
def threads_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List conversation threads."""
    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/threads")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    if isinstance(payload, list):
        table = Table(title="Threads", show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Turns", style="magenta")
        table.add_column("Created", style="dim")
        for t in payload:
            if isinstance(t, dict):
                turns = t.get("turns", [])
                table.add_row(
                    str(t.get("id", "?"))[:12],
                    str(t.get("title", "Untitled"))[:40],
                    str(len(turns) if isinstance(turns, list) else "?"),
                    str(t.get("created_at", ""))[:19],
                )
        console.print(table)
    else:
        console.print(payload)


@threads_app.command("show")
def threads_show(
    thread_id: str = typer.Argument(..., help="Thread ID to display."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show details of a specific thread."""
    config = load_config()
    status_code, payload = api_request(config, "GET", f"/ops/threads/{thread_id}")
    if status_code != 200:
        console.print(f"[red]Thread not found ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    if isinstance(payload, dict):
        console.print(Panel(
            f"Title: {payload.get('title', 'Untitled')}\n"
            f"Workspace: {payload.get('workspace_root', '?')}\n"
            f"Turns: {len(payload.get('turns', []))}",
            title=f"Thread {thread_id[:12]}",
            border_style="cyan",
        ))
        for turn in payload.get("turns", []):
            if not isinstance(turn, dict):
                continue
            agent = turn.get("agent_id", "?")
            items = turn.get("items", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                itype = item.get("type", "?")
                content = str(item.get("content", ""))[:200]
                if itype == "text" and content:
                    prefix = "[bold cyan]>[/bold cyan]" if agent in ("user", "User") else "[bold green]GIMO:[/bold green]"
                    console.print(f"  {prefix} {content}")
                elif itype == "tool_call":
                    meta = item.get("metadata", {})
                    console.print(f"  [dim]\u25b8 {meta.get('tool_name', '?')}[/dim]")
    else:
        console.print(payload)
