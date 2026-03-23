#!/usr/bin/env python3
"""
GIMO MCP Auto-Setup Script.

Registers the GIMO MCP server in the user's various IDE MCP configurations
(Claude Desktop, Cline, Windsurf, Continue, Antigravity)
so it starts automatically.

Usage:
    python scripts/setup_mcp.py           # Auto-detect and install
    python scripts/setup_mcp.py --check   # Verify installation without modifying
    python scripts/setup_mcp.py --remove  # Unregister GIMO from MCP config
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ─── Config Paths ────────────────────────────────────────────────────────────

def _get_platform_paths() -> List[Path]:
    """Locate MCP config files across known IDE integrations."""
    home = Path.home()
    
    # System dependent APPDATA / paths
    if sys.platform == "win32":
        app_data = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        claude_path = app_data / "Claude" / "claude_desktop_config.json"
        cline_path = app_data / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
        cursor_path = app_data / "Cursor" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
    elif sys.platform == "darwin":
        app_data = home / "Library" / "Application Support"
        claude_path = app_data / "Claude" / "claude_desktop_config.json"
        cline_path = app_data / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
        cursor_path = app_data / "Cursor" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
    else:  # Linux
        app_data = home / ".config"
        claude_path = app_data / "Claude" / "claude_desktop_config.json"
        cline_path = app_data / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
        cursor_path = app_data / "Cursor" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"

    candidates = [
        home / ".gemini" / "antigravity" / "mcp_config.json",  # Antigravity
        home / ".gemini" / "mcp_config.json",                   # Gemini direct
        home / ".codeium" / "windsurf" / "mcp_config.json",     # Windsurf
        claude_path,                                            # Claude Desktop
        cline_path,                                             # Cline (VS Code)
        cursor_path,                                            # Cline (Cursor)
    ]
    
    return [p for p in candidates if p.exists() or p.parent.exists()]


def _get_codex_config_path() -> Path:
    """Locate Codex app config.toml."""
    return Path.home() / ".codex" / "config.toml"


def _get_repo_root() -> Path:
    """Get the GIMO repository root (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def _validate_repo_root(repo_root: Path) -> Path:
    """Validate repo root has expected MCP bridge module."""
    resolved = repo_root.expanduser().resolve()
    marker = resolved / "tools" / "gimo_server" / "mcp_bridge" / "server.py"
    if not marker.exists():
        raise FileNotFoundError(
            f"Invalid repo root: {resolved} (missing {marker.relative_to(resolved)})"
        )
    return resolved


def _recommended_python_command() -> str:
    """Prefer current interpreter for reliability across virtualenvs and Windows installs."""
    exe = Path(sys.executable or "").resolve() if sys.executable else None
    if exe and exe.exists():
        return str(exe)
    return "python"


def _load_json_config(config_path: Path) -> Dict[str, Any]:
    """Load JSON config safely; backup invalid files before replacing."""
    if not config_path.exists():
        return {}

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        raise ValueError("Root JSON must be an object")
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = config_path.with_suffix(config_path.suffix + f".bak_{timestamp}")
        try:
            if config_path.exists():
                config_path.replace(backup)
            print(f"[WARN] Invalid config at {config_path}. Backup created: {backup}")
            print(f"       Reason: {exc}")
        except OSError as backup_exc:
            print(f"[WARN] Could not backup invalid config {config_path}: {backup_exc}")
        return {}


# ─── GIMO Server Entry ──────────────────────────────────────────────────────

def _build_gimo_entry(repo_root: Path, python_command: str) -> Dict[str, Any]:
    """Build the GIMO MCP server config entry."""
    # Note: Use the new bridge package entry point
    return {
        "command": python_command,
        "args": ["-m", "tools.gimo_server.mcp_bridge.server"],
        "cwd": str(repo_root),
        "env": {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "ORCH_REPO_ROOT": str(repo_root),
        },
    }


CODEX_GIMO_BEGIN = "# BEGIN GIMO MCP (managed by scripts/setup_mcp.py)"
CODEX_GIMO_END = "# END GIMO MCP (managed by scripts/setup_mcp.py)"


def _codex_launcher_path(repo_root: Path) -> Path:
    return repo_root / "scripts" / "ops" / "codex_stdio_mcp.cmd"


def _build_codex_entry(repo_root: Path) -> str:
    launcher = _codex_launcher_path(repo_root)
    return "\n".join(
        [
            "[mcp_servers.gimo]",
            "enabled = true",
            "required = false",
            "command = 'cmd.exe'",
            f"args = ['/d', '/s', '/c', '{launcher}']",
            f"cwd = '{repo_root}'",
            "startup_timeout_sec = 60.0",
            "tool_timeout_sec = 180.0",
            (
                "env = { "
                f"ORCH_REPO_ROOT = '{repo_root}', "
                "PYTHONIOENCODING = 'utf-8', "
                "PYTHONUTF8 = '1' }"
            ),
        ]
    )


def _strip_codex_managed_block(config_text: str) -> Tuple[str, bool]:
    begin = config_text.find(CODEX_GIMO_BEGIN)
    end = config_text.find(CODEX_GIMO_END)
    if begin == -1 or end == -1 or end < begin:
        return config_text, False
    end += len(CODEX_GIMO_END)
    while end < len(config_text) and config_text[end] in "\r\n":
        end += 1
    new_text = config_text[:begin].rstrip() + "\n"
    if end < len(config_text):
        remainder = config_text[end:].lstrip("\r\n")
        if remainder:
            new_text = new_text.rstrip() + "\n\n" + remainder
    return new_text.rstrip() + "\n", True


def _strip_codex_unmanaged_block(config_text: str) -> Tuple[str, bool]:
    lines = config_text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "[mcp_servers.gimo]":
            start = i
            break
    if start is None:
        return config_text, False

    end = start + 1
    while end < len(lines) and not lines[end].lstrip().startswith("["):
        end += 1

    new_text = "".join(lines[:start] + lines[end:])
    new_text = re.sub(r"\n{3,}", "\n\n", new_text).rstrip() + "\n"
    return new_text, True


def _merge_codex_config_text(existing_text: str, repo_root: Path) -> str:
    stripped, removed = _strip_codex_managed_block(existing_text)
    if not removed:
        stripped, _ = _strip_codex_unmanaged_block(existing_text)

    block = (
        f"{CODEX_GIMO_BEGIN}\n"
        f"{_build_codex_entry(repo_root)}\n"
        f"{CODEX_GIMO_END}\n"
    )
    stripped = stripped.rstrip()
    if stripped:
        return stripped + "\n\n" + block
    return block


def _install_codex(repo_root: Path) -> bool:
    config_path = _get_codex_config_path()
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    merged = _merge_codex_config_text(existing, repo_root)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(merged, encoding="utf-8")
    print(f"[OK] Codex config updated: {config_path}")
    return True


def _remove_codex() -> bool:
    config_path = _get_codex_config_path()
    if not config_path.exists():
        return False

    existing = config_path.read_text(encoding="utf-8")
    stripped, removed = _strip_codex_managed_block(existing)
    if not removed:
        stripped, removed = _strip_codex_unmanaged_block(existing)
    if removed:
        config_path.write_text(stripped, encoding="utf-8")
        print(f"[REMOVED] GIMO removed from {config_path.name}")
    return removed


def _codex_registered(config_path: Path | None = None) -> bool:
    path = config_path or _get_codex_config_path()
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    return CODEX_GIMO_BEGIN in content or "[mcp_servers.gimo]" in content


# ─── Operations ──────────────────────────────────────────────────────────────

def install(repo_root: Path, python_command: str) -> bool:
    """Add or update the GIMO entry in all found MCP configs."""
    paths = _get_platform_paths()
    if not paths:
        # Default to antigravity if no dirs exist
        paths = [Path.home() / ".gemini" / "antigravity" / "mcp_config.json"]

    success_count = 0
    for config_path in paths:
        config: Dict[str, Any] = _load_json_config(config_path)

        servers = config.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            print(f"[WARN] Replacing non-object mcpServers in {config_path.name}")
            servers = {}
            config["mcpServers"] = servers
        if "gimo" in servers:
            print(f"[RELOAD] Updating GIMO in {config_path.name}")
        else:
            print(f"[OK] Adding GIMO to {config_path.name}")

        servers["gimo"] = _build_gimo_entry(repo_root, python_command)

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        success_count += 1
        
    print("\n[OK] Install summary:")
    print(f"   Configs updated: {success_count}")
    print(f"   Command: {python_command} -m tools.gimo_server.mcp_bridge.server")
    print(f"   CWD:     {repo_root}")
    
    print("\\n   [CONTINUE / JETBRAINS MANUAL SETUP]")
    print("   If you are using Continue.dev, add this to your ~/.continue/config.json in the mcpServers array:")
    print("   {")
    print('      "name": "gimo",')
    print(f'      "command": "{python_command}",')
    print('      "args": ["-m", "tools.gimo_server.mcp_bridge.server"],')
    print(f'      "env": {{"ORCH_REPO_ROOT": "{str(repo_root)}"}}')
    print("   }")
    _install_codex(repo_root)
    print("\\n[DONE] Restart your IDE/editor to activate GIMO MCP.")
    return True


def check(repo_root: Optional[Path] = None) -> bool:
    """Verify GIMO is registered in the MCP config."""
    paths = _get_platform_paths()
    found = False
    expected_root = str(repo_root) if repo_root else None
    
    for config_path in paths:
        if not config_path.exists():
            continue

        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            servers = config.get("mcpServers", {})
            if "gimo" in servers:
                found = True
                entry = servers.get("gimo", {})
                cwd = entry.get("cwd")
                status = "OK"
                if expected_root and cwd and str(cwd) != expected_root:
                    status = "WARN"
                print(f"[{status}] GIMO registered in {config_path.name} (cwd={cwd})")
        except:
            pass

    codex_path = _get_codex_config_path()
    if _codex_registered(codex_path):
        found = True
        print(f"[OK] GIMO registered in Codex ({codex_path})")

    if not found:
        print("[ERROR] GIMO not registered in any known config paths.")
        print("   Run: python scripts/setup_mcp.py")
        return False
    return True


def remove() -> bool:
    """Remove GIMO from the MCP config."""
    paths = _get_platform_paths()
    removed = 0
    
    for config_path in paths:
        if not config_path.exists():
            continue

        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            servers = config.get("mcpServers", {})
            if "gimo" in servers:
                del servers["gimo"]
                config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                print(f"[REMOVED] GIMO removed from {config_path.name}")
                removed += 1
        except:
            pass

    codex_removed = _remove_codex()
    if removed == 0:
        if codex_removed:
            return True
        print("[INFO] GIMO was not registered in any known config.")
    return True


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install/check/remove GIMO MCP wiring.")
    parser.add_argument("--check", action="store_true", help="Verify MCP registration")
    parser.add_argument("--remove", action="store_true", help="Remove GIMO from MCP configs")
    parser.add_argument(
        "--repo-root",
        type=str,
        default=None,
        help="Absolute or relative path to GIMO repo root (auto-detected by default)",
    )
    parser.add_argument(
        "--python-command",
        type=str,
        default=None,
        help="Python executable to write in MCP config (default: current interpreter)",
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    raw_repo_root = Path(args.repo_root) if args.repo_root else _get_repo_root()
    repo_root = _validate_repo_root(raw_repo_root)
    python_command = args.python_command or _recommended_python_command()

    if args.check:
        ok = check(repo_root=repo_root)
        sys.exit(0 if ok else 1)
    elif args.remove:
        remove()
    else:
        install(repo_root, python_command)


if __name__ == "__main__":
    main()
