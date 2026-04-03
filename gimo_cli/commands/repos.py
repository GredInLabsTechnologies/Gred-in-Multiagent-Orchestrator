"""Repository management commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from gimo_cli import app, console
from gimo_cli.api import api_request
from gimo_cli.config import load_config, project_root
from gimo_cli.stream import emit_output

repos_app = typer.Typer(name="repos", help="Repository management.")
app.add_typer(repos_app, name="repos")


@repos_app.command("list")
def repos_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List known repositories."""
    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/repos")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    if isinstance(payload, list):
        table = Table(title="Repositories", show_header=True)
        table.add_column("Path", style="cyan")
        table.add_column("Active", style="green")
        for repo in payload:
            if isinstance(repo, dict):
                table.add_row(str(repo.get("path", "?")), str(repo.get("active", "")))
            else:
                table.add_row(str(repo), "")
        console.print(table)
    elif isinstance(payload, dict):
        repos = payload.get("repos") or payload.get("repositories") or []
        active = payload.get("active") or payload.get("selected")
        if repos:
            for r in repos:
                marker = " [green]*[/green]" if str(r) == str(active) else ""
                console.print(f"  {r}{marker}")
        else:
            console.print_json(data=payload)
    else:
        console.print_json(data=payload) if isinstance(payload, (dict, list)) else console.print(f"[dim]{payload}[/dim]")


@repos_app.command("select")
def repos_select(
    path: str = typer.Argument(..., help="Repository path to select."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Legacy host-path selection is not part of the canonical terminal flow."""
    load_config()
    requested = str(Path(path).resolve())
    canonical_message = (
        "Legacy host-path repo selection has been removed from the canonical terminal flow. "
        "Use the current workspace contract instead: change into the target repository and run "
        "'gimo init', then start threads from that workspace."
    )
    payload = {
        "status": "legacy_removed",
        "requested_path": requested,
        "detail": canonical_message,
        "canonical_flow": {
            "workspace_root": str(project_root()),
            "command": "gimo init",
        },
    }
    if json_output:
        emit_output(payload, json_output=True)
        raise typer.Exit(1)
    console.print(f"[red]{canonical_message}[/red]")
    raise typer.Exit(1)
