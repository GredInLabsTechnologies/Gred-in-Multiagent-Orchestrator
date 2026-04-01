"""Chat and TUI commands."""

from __future__ import annotations

import typer

from gimo_cli import app, console
from gimo_cli.chat import interactive_chat
from gimo_cli.config import (
    config_path,
    default_config,
    ensure_project_dirs,
    load_config,
    save_config,
)


@app.command()
def tui(
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug/verbose render mode"),
) -> None:
    """Launch the experimental Textual UI."""
    try:
        config = load_config()
    except Exception:
        ensure_project_dirs()
        config = load_config()

    if "orchestrator" not in config:
        config["orchestrator"] = {}
    config["orchestrator"]["verbose"] = verbose or config["orchestrator"].get("verbose", False)

    from gimo_tui import GimoApp
    console.print("[dim]Launching TUI...[/dim]")
    app_tui = GimoApp(config=config, thread_id="tui_default")
    app_tui.verbose = config["orchestrator"]["verbose"]
    app_tui.run()


@app.command()
def chat(
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug/verbose render mode"),
) -> None:
    """Interactive agentic chat session with GIMO orchestrator."""
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
