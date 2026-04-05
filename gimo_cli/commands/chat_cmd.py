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
    from gimo_cli.api import api_request
    from gimo_cli.config import project_root

    # Create a real thread via the backend (not a hardcoded ID)
    ws_root = str(project_root())
    status_code, thread_data = api_request(
        config, "POST", "/ops/threads",
        params={"workspace_root": ws_root, "title": "TUI Agentic Session"},
    )
    if status_code == 201 and isinstance(thread_data, dict):
        thread_id = str(thread_data.get("id") or "tui_fallback")
    else:
        # Fallback if server is not running — TUI will show error on first chat
        thread_id = "tui_fallback"

    console.print("[dim]Launching TUI...[/dim]")
    app_tui = GimoApp(config=config, thread_id=thread_id)
    app_tui.verbose = config["orchestrator"]["verbose"]
    app_tui.run()


@app.command()
def chat(
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug/verbose render mode"),
    message: str = typer.Option(None, "--message", "-m", help="Send a single message and exit (non-interactive mode)."),
    thread: str = typer.Option(None, "--thread", "-t", help="Continue an existing thread by ID."),
    execute: bool = typer.Option(False, "--execute", "-x", help="Enable file mutation tools (workspace_safe policy)."),
    workspace: str = typer.Option(None, "--workspace", "-w", help="Target workspace directory for file operations."),
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
            # Create a new thread with title from first message and workspace
            ws_root = workspace or "."
            thread_title = (message or "")[:60] or None
            _, thread_data = api_request(
                config, "POST", "/ops/threads",
                params={"workspace_root": ws_root},
                json_body={"title": thread_title},
            )
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

    # Interactive mode: launch TUI (unified terminal experience)
    # CLI's interactive_chat() remains available as fallback if Textual is unavailable
    try:
        from gimo_tui import GimoApp
        from gimo_cli.api import api_request
        from gimo_cli.config import project_root as _project_root

        ws_root = str(_project_root())
        status_code, thread_data = api_request(
            config, "POST", "/ops/threads",
            params={"workspace_root": ws_root, "title": "Chat Agentic Session"},
        )
        if status_code == 201 and isinstance(thread_data, dict):
            tid = str(thread_data.get("id") or "chat_fallback")
        else:
            tid = "chat_fallback"

        app_tui = GimoApp(config=config, thread_id=tid)
        app_tui.verbose = config["orchestrator"]["verbose"]
        app_tui.run()
    except ImportError:
        # Textual not available — fall back to Rich-based CLI chat
        interactive_chat(config)
