import os
from pathlib import Path

DEFAULT_API_BASE_URL = os.environ.get("GIMO_API_URL") or os.environ.get("ORCH_BASE_URL") or "http://127.0.0.1:9325"
DEFAULT_TIMEOUT_SECONDS = 15.0  # Fallback mínimo — server-driven timeout es el preferred path
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_WATCH_TIMEOUT_SECONDS = 30.0

# DEFAULT_PREFERRED_MODEL removed — model selection is server-driven via GICS inventory

# ServerBond home directory
GIMO_HOME_DIR = Path(os.environ.get("GIMO_HOME", str(Path.home() / ".gimo")))

DEFAULT_EXCLUDE_DIRS = [
    ".git",
    "node_modules",
    ".venv",
    "__pycache__",
    "dist",
    "build",
]

ACTIVE_RUN_STATUSES = frozenset({
    "pending",
    "running",
    "awaiting_subagents",
    "awaiting_review",
    "MERGE_LOCKED",
    "WORKER_CRASHED_RECOVERABLE",
    "HUMAN_APPROVAL_REQUIRED",
})

TERMINAL_RUN_STATUSES = frozenset({
    "done",
    "error",
    "cancelled",
    "MERGE_CONFLICT",
    "VALIDATION_FAILED_TESTS",
    "VALIDATION_FAILED_LINT",
    "RISK_SCORE_TOO_HIGH",
    "BASELINE_TAMPER_DETECTED",
    "PIPELINE_TIMEOUT",
    "WORKTREE_CORRUPTED",
    "ROLLBACK_EXECUTED",
})
