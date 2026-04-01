"""GIMO CLI entry point.

All implementation lives in the ``gimo_cli`` package.
This file is kept as a thin launcher with backwards-compatible re-exports
so that existing tests and satellite modules (gimo_tui.py, etc.) that
``from gimo import _api_request`` continue to work.
"""

from __future__ import annotations

# ── canonical entry ──────────────────────────────────────────────────
from gimo_cli import app, console  # noqa: F401

# ── re-exports: api layer ────────────────────────────────────────────
from gimo_cli.api import (  # noqa: F401
    api_request as _api_request,
    api_settings as _api_settings,
    fetch_capabilities as _fetch_capabilities,
    provider_config_request as _provider_config_request,
    resolve_token as _resolve_token,
    smart_timeout as _smart_timeout,
)

# ── re-exports: config / paths ───────────────────────────────────────
from gimo_cli.config import (  # noqa: F401
    DEFAULT_API_BASE_URL,
    load_config as _load_config,
    save_config as _save_config,
    project_root as _project_root,
    plans_dir as _plans_dir,
    runs_dir as _runs_dir,
    history_dir as _history_dir,
    config_path as _config_path,
    ensure_project_dirs as _ensure_project_dirs,
    default_config as _default_config,
)

# ── re-exports: bond ─────────────────────────────────────────────────
from gimo_cli.bond import (  # noqa: F401
    load_bond as _load_bond,
    save_bond as _save_bond,
    delete_bond as _delete_bond,
)

# ── re-exports: stream / helpers ─────────────────────────────────────
from gimo_cli.stream import (  # noqa: F401
    emit_output as _emit_output,
    write_json as _write_json,
    terminal_status as _terminal_status,
    poll_run as _poll_run,
    stream_events as _stream_events,
    git_command as _git_command,
)

# ── re-exports: chat ─────────────────────────────────────────────────
from gimo_cli.chat import (  # noqa: F401
    interactive_chat as _interactive_chat,
    handle_chat_slash_command as _handle_chat_slash_command,
    ConsoleTerminalSurface,
)


if __name__ == "__main__":
    app()
