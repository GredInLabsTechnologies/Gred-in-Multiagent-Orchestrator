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
    message: str = typer.Option(None, "--message", "-m", help="Send a single message and exit (non-interactive mode)."),
    thread: str = typer.Option(None, "--thread", "-t", help="Continue an existing thread by ID."),
    execute: bool = typer.Option(False, "--execute", "-x", help="Enable file mutation tools (workspace_safe policy)."),
) -> None:
    """Interactive agentic chat session with GIMO orchestrator.

    Use --message / -m for non-interactive single-turn mode:
      gimo chat -m "What files are in this project?"

    Use --execute / -x to allow file writes:
      gimo chat -m "Create calculator.py" -x

    Use --thread / -t to continue an existing thread:
      gimo chat -m "Add tests" -t thread_abc12345
    """
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

    if message:
        # Single-turn mode: send message via API and print response
        from gimo_cli.api import api_request

        if thread:
            thread_id = thread
        else:
            # Create a new thread
            _, thread_data = api_request(config, "POST", "/ops/threads", params={"workspace_root": "."})
            thread_id = thread_data.get("id", "") if isinstance(thread_data, dict) else ""
            if not thread_id:
                console.print("[red]Failed to create thread for single-turn chat[/red]")
                raise typer.Exit(1)

        # If --execute, set policy to workspace_safe via config endpoint
        if execute:
            api_request(
                config, "POST", f"/ops/threads/{thread_id}/config",
                json_body={"execution_policy": "workspace_safe"},
            )

        _, resp = api_request(config, "POST", f"/ops/threads/{thread_id}/chat", json_body={"content": message})
        if isinstance(resp, dict):
            content = resp.get("response") or resp.get("content") or ""
            if verbose:
                tool_logs = resp.get("tool_calls_log") or []
                for tl in tool_logs:
                    status = tl.get("status", "?")
                    name = tl.get("name", "?")
                    msg = tl.get("message", "")[:80]
                    style = "green" if status == "success" else "red"
                    console.print(f"  [{style}][{status}] {name}[/{style}] {msg}")
            console.print(content)
            if verbose and thread_id:
                console.print(f"[dim]thread: {thread_id}[/dim]")
        else:
            console.print(str(resp))
        return

    interactive_chat(config)
