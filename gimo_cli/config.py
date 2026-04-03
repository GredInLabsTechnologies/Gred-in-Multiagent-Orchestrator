"""CLI configuration, constants, parsers, and policies."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import typer

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    yaml = None  # type: ignore

from gimo_cli import console

# ── Constants (from cli_constants.py) ─────────────────────────────────────────

DEFAULT_API_BASE_URL = os.environ.get("GIMO_API_URL") or os.environ.get("ORCH_BASE_URL") or "http://127.0.0.1:9325"
DEFAULT_TIMEOUT_SECONDS = 180.0  # Increased from 15s to 180s - plan generation can take 30-60s
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_WATCH_TIMEOUT_SECONDS = 180.0  # Increased from 30s to 180s for consistency
GIMO_HOME_DIR = Path(os.environ.get("GIMO_HOME", str(Path.home() / ".gimo")))

DEFAULT_EXCLUDE_DIRS = [
    ".git", "node_modules", ".venv", "__pycache__", "dist", "build",
]

ACTIVE_RUN_STATUSES = frozenset({
    "pending", "running", "awaiting_subagents", "awaiting_review",
    "MERGE_LOCKED", "WORKER_CRASHED_RECOVERABLE", "HUMAN_APPROVAL_REQUIRED",
})

TERMINAL_RUN_STATUSES = frozenset({
    "done", "error", "cancelled", "MERGE_CONFLICT",
    "VALIDATION_FAILED_TESTS", "VALIDATION_FAILED_LINT",
    "RISK_SCORE_TOO_HIGH", "BASELINE_TAMPER_DETECTED",
    "PIPELINE_TIMEOUT", "WORKTREE_CORRUPTED", "ROLLBACK_EXECUTED",
})

# ── Policies (from cli_policies.py) ───────────────────────────────────────────

CODE_EDITING_TOOL_NAMES = frozenset({"write_file", "search_replace", "patch_file"})


def get_budget_color(rem_pct: float | None) -> str:
    if rem_pct is None:
        return "green"
    if rem_pct < 20:
        return "red"
    if rem_pct < 50:
        return "yellow"
    return "green"


# ── Parsers (from cli_parsers.py) ─────────────────────────────────────────────

def parse_yes_no(text: str) -> bool:
    if not text:
        return False
    return text.strip().lower() in {"y", "yes", "si", "sí", "approve"}


def parse_plan_action(text: str) -> str:
    if not text:
        return "reject"
    val = text.strip().lower()
    if val in {"y", "yes", "si", "sí", "approve"}:
        return "approve"
    if val in {"m", "modify", "edit"}:
        return "modify"
    return "reject"


def is_terminal_status(status: str, active_statuses: frozenset, terminal_statuses: frozenset) -> bool:
    return status in terminal_statuses


# ── Project/config helpers ────────────────────────────────────────────────────

def project_root() -> Path:
    try:
        probe = subprocess.run(["git", "rev-parse", "--show-toplevel"], text=True, capture_output=True, check=True)
        return Path(probe.stdout.strip())
    except Exception:
        return Path.cwd()


def gimo_dir() -> Path:
    return project_root() / ".gimo"


def config_path() -> Path:
    return gimo_dir() / "config.yaml"


def plans_dir() -> Path:
    return gimo_dir() / "plans"


def history_dir() -> Path:
    return gimo_dir() / "history"


def runs_dir() -> Path:
    return gimo_dir() / "runs"


def ensure_project_dirs() -> None:
    """Ensure .gimo/ workspace structure exists. Delegates to WorkspaceContract."""
    try:
        from tools.gimo_server.services.workspace.workspace_contract import WorkspaceContract
        WorkspaceContract.ensure(project_root())
    except ImportError:
        # Fallback if server package not available (e.g. standalone CLI)
        for path in (gimo_dir(), plans_dir(), history_dir(), runs_dir()):
            path.mkdir(parents=True, exist_ok=True)


def default_config() -> dict[str, Any]:
    return {
        "orchestrator": {
            "budget_limit_usd": 10.0,
            "verbose": False,
            "auto_run_eligible": True,
        },
        "repository": {
            "name": project_root().name,
            "workspace_root": str(project_root()),
            "index_depth": 3,
            "exclude_dirs": DEFAULT_EXCLUDE_DIRS,
        },
        "api": {
            "base_url": DEFAULT_API_BASE_URL,
            "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        },
        "providers": {
            "anthropic": {"enabled": True},
            "openai": {"enabled": False},
        },
    }


def save_config(config: dict[str, Any]) -> None:
    if not YAML_AVAILABLE or not yaml:
        console.print("[red]PyYAML is required. Install with: pip install PyYAML>=6.0.2[/red]")
        raise typer.Exit(1)
    ensure_project_dirs()
    config_path().write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def _load_global_config() -> dict[str, Any]:
    if not YAML_AVAILABLE or not yaml:
        return {}
    from gimo_cli.bond import gimo_home
    global_cfg_path = gimo_home() / "config.yaml"
    if not global_cfg_path.exists():
        return {}
    try:
        cfg = yaml.safe_load(global_cfg_path.read_text(encoding="utf-8"))
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(require_project: bool = True) -> dict[str, Any]:
    """Load config with cascading merge: global (~/.gimo) -> project (.gimo) -> result."""
    if not YAML_AVAILABLE or not yaml:
        console.print("[red]PyYAML is required. Install with: pip install PyYAML>=6.0.2[/red]")
        raise typer.Exit(1)

    global_config = _load_global_config()

    if not config_path().exists():
        if require_project:
            console.print("[red]Project not initialized. Run 'gimo init' first.[/red]")
            raise typer.Exit(1)
        else:
            return global_config if global_config else {}

    ensure_project_dirs()
    local_content = yaml.safe_load(config_path().read_text(encoding="utf-8")) or {}
    if not isinstance(local_content, dict):
        console.print("[red]Invalid .gimo/config.yaml format.[/red]")
        raise typer.Exit(1)

    return _deep_merge(global_config, local_content)


def read_token_from_env_file() -> str | None:
    env_path = project_root() / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key.strip() in {"GIMO_TOKEN", "ORCH_TOKEN"}:
            return value.strip().strip('"').strip("'")
    return None
