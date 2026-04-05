"""Surface management commands: connect, list, disconnect.

Auto-discovers and configures MCP connections for any surface
(Claude Desktop, VS Code, Cursor, etc.) without hardcoded paths.
"""
from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from gimo_cli import app, console
from gimo_cli.bond import gimo_home

surface_app = typer.Typer(help="Manage surface connections (MCP clients)")
app.add_typer(surface_app, name="surface")


# ── Surface config discovery ─────────────────────────────────────────────

def _repo_root() -> Path:
    """Auto-discover the GIMO repo root."""
    # 1. Env var
    env_root = os.environ.get("ORCH_REPO_ROOT", "").strip()
    if env_root and Path(env_root).is_dir():
        return Path(env_root).resolve()

    # 2. Walk up from this file
    candidate = Path(__file__).resolve()
    for _ in range(10):
        candidate = candidate.parent
        if (candidate / "tools" / "gimo_server" / "mcp_bridge" / "server.py").exists():
            return candidate

    # 3. CWD
    cwd = Path.cwd()
    if (cwd / "tools" / "gimo_server").exists():
        return cwd

    raise typer.BadParameter(
        "Cannot find GIMO repo root. Set ORCH_REPO_ROOT or run from within the repo."
    )


def _python_exe() -> str:
    """Find the best Python executable for MCP server."""
    root = _repo_root()

    # 1. Venv in repo
    for venv_dir in [".venv", "venv", "env"]:
        if platform.system() == "Windows":
            candidate = root / venv_dir / "Scripts" / "python.exe"
        else:
            candidate = root / venv_dir / "bin" / "python"
        if candidate.exists():
            return str(candidate)

    # 2. Current interpreter
    return sys.executable


def _mcp_server_entry() -> dict:
    """Build the MCP server config entry — portable, no hardcoded paths.

    Uses PYTHONPATH instead of cwd because Claude Desktop does NOT support
    the cwd field. PYTHONPATH lets `python -m tools.gimo_server...` find
    the module from any working directory.
    """
    root = _repo_root()
    python = _python_exe()

    return {
        "command": python,
        "args": ["-m", "tools.gimo_server.mcp_bridge.server"],
        "env": {
            "PYTHONPATH": str(root),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "ORCH_REPO_ROOT": str(root),
        },
    }


# ── Surface config paths ─────────────────────────────────────────────────

SURFACE_CONFIGS = {
    "claude_desktop": {
        "name": "Claude Desktop",
        "paths": {
            "Windows": [
                Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json",
            ],
            "Darwin": [
                Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            ],
            "Linux": [
                Path.home() / ".config" / "claude" / "claude_desktop_config.json",
            ],
        },
        "key": "mcpServers",
        "server_name": "gimo",
    },
    "claude_code": {
        "name": "Claude Code",
        "paths": {
            "Windows": [
                Path.home() / ".claude" / "settings.json",
                Path.home() / ".claude.json",
            ],
            "Darwin": [
                Path.home() / ".claude" / "settings.json",
            ],
            "Linux": [
                Path.home() / ".claude" / "settings.json",
            ],
        },
        "key": "mcpServers",
        "server_name": "gimo",
    },
    "vscode": {
        "name": "VS Code",
        "paths": {
            "Windows": [
                Path(os.environ.get("APPDATA", "")) / "Code" / "User" / "settings.json",
            ],
            "Darwin": [
                Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json",
            ],
            "Linux": [
                Path.home() / ".config" / "Code" / "User" / "settings.json",
            ],
        },
        "key": "mcp.servers",
        "server_name": "gimo",
    },
    "cursor": {
        "name": "Cursor",
        "paths": {
            "Windows": [
                Path(os.environ.get("APPDATA", "")) / "Cursor" / "User" / "settings.json",
            ],
            "Darwin": [
                Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "settings.json",
            ],
            "Linux": [
                Path.home() / ".config" / "Cursor" / "User" / "settings.json",
            ],
        },
        "key": "mcp.servers",
        "server_name": "gimo",
    },
}


def _find_config_path(surface_id: str) -> Optional[Path]:
    """Find the config file for a surface on this OS."""
    surface = SURFACE_CONFIGS.get(surface_id)
    if not surface:
        return None

    system = platform.system()
    candidates = surface["paths"].get(system, [])
    for path in candidates:
        if path.exists():
            return path

    # Return first candidate even if it doesn't exist (we'll create it)
    return candidates[0] if candidates else None


def _read_config(path: Path) -> dict:
    """Read a JSON config file, returning empty dict if missing/invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config(path: Path, config: dict) -> None:
    """Write JSON config, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def _set_nested(d: dict, dotted_key: str, value: dict, server_name: str) -> None:
    """Set (or replace) a server entry in a nested dict using dotted key path."""
    keys = dotted_key.split(".")
    current = d
    for key in keys[:-1]:
        current = current.setdefault(key, {})
    servers = current.setdefault(keys[-1], {})
    servers[server_name] = value  # Full replace — removes stale keys like cwd


def _remove_nested(d: dict, dotted_key: str, server_name: str) -> bool:
    """Remove a server entry from a nested dict. Returns True if removed."""
    keys = dotted_key.split(".")
    current = d
    for key in keys[:-1]:
        if key not in current:
            return False
        current = current[key]
    last = keys[-1]
    if last in current and server_name in current[last]:
        del current[last][server_name]
        return True
    return False


# ── Commands ──────────────────────────────────────────────────────────────

@surface_app.command("connect")
def connect(
    surface: str = typer.Argument(
        ...,
        help="Surface to connect: claude_desktop, claude_code, vscode, cursor, or 'all'",
    ),
):
    """Auto-configure a surface to use GIMO as MCP server."""
    targets = list(SURFACE_CONFIGS.keys()) if surface == "all" else [surface]

    for target in targets:
        if target not in SURFACE_CONFIGS:
            console.print(f"[red]Unknown surface: {target}[/red]")
            console.print(f"Available: {', '.join(SURFACE_CONFIGS.keys())}")
            continue

        try:
            entry = _mcp_server_entry()
            config_path = _find_config_path(target)
            if not config_path:
                console.print(f"[yellow]{target}: Config path not found for {platform.system()}[/yellow]")
                continue

            config = _read_config(config_path)
            surface_def = SURFACE_CONFIGS[target]
            _set_nested(config, surface_def["key"], entry, surface_def["server_name"])
            _write_config(config_path, config)

            console.print(
                f"[green]Connected:[/green] {surface_def['name']} <- GIMO MCP\n"
                f"  Config: {config_path}\n"
                f"  Python: {entry['command']}\n"
                f"  Repo:   {entry['cwd']}"
            )
        except Exception as exc:
            console.print(f"[red]{target}: {exc}[/red]")


@surface_app.command("disconnect")
def disconnect(
    surface: str = typer.Argument(
        ...,
        help="Surface to disconnect: claude_desktop, claude_code, vscode, cursor, or 'all'",
    ),
):
    """Remove GIMO MCP server from a surface config."""
    targets = list(SURFACE_CONFIGS.keys()) if surface == "all" else [surface]

    for target in targets:
        if target not in SURFACE_CONFIGS:
            continue

        config_path = _find_config_path(target)
        if not config_path or not config_path.exists():
            continue

        config = _read_config(config_path)
        surface_def = SURFACE_CONFIGS[target]
        if _remove_nested(config, surface_def["key"], surface_def["server_name"]):
            _write_config(config_path, config)
            console.print(f"[yellow]Disconnected:[/yellow] {surface_def['name']}")
        else:
            console.print(f"[dim]{surface_def['name']}: Not connected[/dim]")


@surface_app.command("list")
def list_surfaces():
    """Show all detected surfaces and their connection status."""
    table = Table(title="GIMO Surface Connections")
    table.add_column("Surface", style="bold")
    table.add_column("Config Path")
    table.add_column("Status")
    table.add_column("Python")

    for surface_id, surface_def in SURFACE_CONFIGS.items():
        config_path = _find_config_path(surface_id)
        if not config_path:
            table.add_row(surface_def["name"], "Not found", "[dim]N/A[/dim]", "")
            continue

        config = _read_config(config_path) if config_path.exists() else {}

        # Check if GIMO is configured
        keys = surface_def["key"].split(".")
        current = config
        for k in keys:
            current = current.get(k, {}) if isinstance(current, dict) else {}
        is_connected = surface_def["server_name"] in current if isinstance(current, dict) else False

        status = "[green]Connected[/green]" if is_connected else "[dim]Not connected[/dim]"

        python_path = ""
        if is_connected and isinstance(current, dict):
            server_cfg = current.get(surface_def["server_name"], {})
            python_path = server_cfg.get("command", "")

        table.add_row(
            surface_def["name"],
            str(config_path) if config_path.exists() else f"[dim]{config_path}[/dim]",
            status,
            python_path,
        )

    console.print(table)

    # Show auto-discovered info
    try:
        root = _repo_root()
        python = _python_exe()
        console.print(f"\n[bold]Auto-discovered:[/bold]")
        console.print(f"  Repo root: {root}")
        console.print(f"  Python:    {python}")
        console.print(f"  OS:        {platform.system()} {platform.release()}")
    except Exception as exc:
        console.print(f"\n[red]Auto-discovery failed: {exc}[/red]")


@surface_app.command("config")
def show_config():
    """Print the MCP server config that would be written (for manual setup)."""
    try:
        entry = _mcp_server_entry()
        console.print_json(json.dumps({"mcpServers": {"gimo": entry}}, indent=2))
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
