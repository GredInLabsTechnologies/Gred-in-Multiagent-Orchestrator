"""Core commands: main callback, init, status."""

from __future__ import annotations


import typer
from rich.panel import Panel

from gimo_cli import app, console
from gimo_cli.chat import ConsoleTerminalSurface, interactive_chat
from gimo_cli.config import (
    config_path,
    default_config,
    ensure_project_dirs,
    history_dir,
    load_config,
    plans_dir,
    project_root,
    runs_dir,
    save_config,
)
from gimo_cli.stream import emit_output
from terminal_command_executor import fetch_operator_status_snapshot
from gimo_cli.api import api_request, resolve_token


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug/verbose render mode"),
) -> None:
    """GIMO: Gred In Multiagent Orchestrator.

    Run without a subcommand to start an interactive agentic chat session.
    """
    if ctx.invoked_subcommand is not None:
        return

    try:
        config = load_config()
    except typer.Exit:
        ensure_project_dirs()
        if not config_path().exists():
            save_config(default_config())
        config = load_config()

    if "orchestrator" not in config:
        config["orchestrator"] = {}
    config["orchestrator"]["verbose"] = verbose or config["orchestrator"].get("verbose", False)

    interactive_chat(config)


@app.command()
def init(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Initialize the current workspace for GIMO CLI usage."""
    ensure_project_dirs()

    if config_path().exists():
        payload = {
            "initialized": True,
            "config_path": str(config_path()),
            "plans_dir": str(plans_dir()),
            "history_dir": str(history_dir()),
            "runs_dir": str(runs_dir()),
            "already_exists": True,
        }
        if json_output:
            emit_output(payload, json_output=True)
            return
        console.print(Panel(f"Config already exists at {config_path()}", title="GIMO Init", border_style="yellow"))
        return

    config = default_config()
    save_config(config)

    # Register the workspace with the backend so it appears in /ops/repos
    try:
        _cfg = load_config()
        api_request(_cfg, "POST", "/ops/repos/register", json_body={
            "path": str(project_root()),
            "name": project_root().name,
        })
    except Exception:
        pass  # Server might not be running during init — that's OK

    payload = {
        "initialized": True,
        "config_path": str(config_path()),
        "plans_dir": str(plans_dir()),
        "history_dir": str(history_dir()),
        "runs_dir": str(runs_dir()),
        "already_exists": False,
    }
    if json_output:
        emit_output(payload, json_output=True)
        return
    console.print(
        Panel(
            "\n".join([
                "[bold green]Workspace initialized.[/bold green]",
                f"Config: {config_path()}",
                f"Plans: {plans_dir()}",
                f"History: {history_dir()}",
                f"Runs: {runs_dir()}",
            ]),
            title="GIMO Init",
            border_style="green",
        )
    )


@app.command()
def status(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Render the authoritative backend status snapshot."""
    config = load_config(require_project=False)

    token = resolve_token("operator", config)
    if not config and not token:
        from gimo_cli.stream import git_command
        repo_name = project_root().name
        branch_res = git_command(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch_res.stdout.strip() if branch_res.returncode == 0 else "unknown"
        lines = [
            f"[bold]Repo[/bold]: {repo_name}  branch: [cyan]{branch}[/cyan]",
            "[red][!] Workspace not initialized. Run 'gimo init'.[/red]",
        ]
        if json_output:
            emit_output({}, json_output=True)
            return
        console.print(Panel("\n".join(lines), title="GIMO Status", border_style="red"))
        return

    status_code, payload = fetch_operator_status_snapshot(config, api_request)
    if status_code != 200 or not isinstance(payload, dict):
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        console.print(f"[red]Failed to fetch authoritative status ({status_code}): {detail}[/red]")
        raise typer.Exit(1)

    if json_output:
        emit_output(payload, json_output=True)
        return

    ConsoleTerminalSurface(workspace_root=str(project_root())).render_status_snapshot(payload)
