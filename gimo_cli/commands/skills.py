"""Skills commands."""

from __future__ import annotations

import typer
from rich.table import Table

from gimo_cli import app, console
from gimo_cli.api import api_request
from gimo_cli.config import load_config
from gimo_cli.stream import emit_output

skills_app = typer.Typer(name="skills", help="List and execute registered skills.")
app.add_typer(skills_app, name="skills")


@skills_app.command("list")
def skills_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List registered skills."""
    config = load_config()
    status_code, payload = api_request(config, "GET", "/ops/skills")
    if status_code != 200:
        console.print(f"[red]Failed ({status_code}): {payload}[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_output(payload, json_output=True)
        return
    if isinstance(payload, list):
        table = Table(title="Skills", show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Description", style="dim")
        for skill in payload:
            if isinstance(skill, dict):
                table.add_row(
                    str(skill.get("id", "?")),
                    str(skill.get("name", "?")),
                    str(skill.get("description", ""))[:60],
                )
        console.print(table)
    else:
        console.print(payload)


@skills_app.command("run")
def skills_run(
    skill_id: str = typer.Argument(..., help="Skill ID to execute."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Execute a registered skill."""
    config = load_config()
    with console.status("[bold green]Executing skill..."):
        status_code, payload = api_request(config, "POST", f"/ops/skills/{skill_id}/execute")
    if json_output:
        emit_output({"status_code": status_code, "result": payload}, json_output=True)
        return
    if status_code == 200:
        console.print(f"[green]Skill '{skill_id}' executed successfully.[/green]")
        if isinstance(payload, dict):
            console.print_json(data=payload)
    else:
        console.print(f"[red]Execution failed ({status_code}): {payload}[/red]")
