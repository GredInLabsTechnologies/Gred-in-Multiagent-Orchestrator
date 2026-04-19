"""GIMO CLI — Gred In Multiagent Orchestrator command-line interface."""

from __future__ import annotations

import sys

import typer
from rich.console import Console


def _setup_windows_console():
    """Enable UTF-8 output and VT processing on Windows."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


_setup_windows_console()

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
from gimo_cli.commands import server  # noqa: E402,F401
from gimo_cli.commands import surface  # noqa: E402,F401
from gimo_cli.commands import discover  # noqa: E402,F401
from gimo_cli.commands import runtime  # noqa: E402,F401

__all__ = ["app", "console"]
