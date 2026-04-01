"""GIMO CLI — Gred In Multiagent Orchestrator command-line interface."""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    name="gimo",
    help="GIMO: Gred In Multiagent Orchestrator",
    add_completion=True,
    invoke_without_command=True,
)
console = Console()

# Register all command modules (side-effect imports)
from gimo_cli.commands import core  # noqa: E402,F401
from gimo_cli.commands import plan  # noqa: E402,F401
from gimo_cli.commands import run  # noqa: E402,F401
from gimo_cli.commands import chat_cmd  # noqa: E402,F401
from gimo_cli.commands import ops  # noqa: E402,F401
from gimo_cli.commands import auth  # noqa: E402,F401
from gimo_cli.commands import providers  # noqa: E402,F401
from gimo_cli.commands import trust  # noqa: E402,F401
from gimo_cli.commands import mastery  # noqa: E402,F401
from gimo_cli.commands import skills  # noqa: E402,F401
from gimo_cli.commands import repos  # noqa: E402,F401
from gimo_cli.commands import threads  # noqa: E402,F401
from gimo_cli.commands import observe  # noqa: E402,F401

__all__ = ["app", "console"]
