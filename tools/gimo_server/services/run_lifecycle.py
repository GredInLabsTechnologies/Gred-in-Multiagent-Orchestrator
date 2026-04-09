from __future__ import annotations

ACTIVE_RUN_STATUSES = frozenset(
    {
        "pending",
        "running",
        "awaiting_subagents",
        "awaiting_review",
        "MERGE_LOCKED",
        "WORKER_CRASHED_RECOVERABLE",
        "HUMAN_APPROVAL_REQUIRED",
        "AWAITING_MERGE",
    }
)

RESUMABLE_RUN_STATUSES = frozenset({"HUMAN_APPROVAL_REQUIRED"})

TERMINAL_RUN_STATUSES = frozenset(
    {
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
    }
)


def normalize_run_status(status: str | None) -> str:
    return str(status or "").strip()


def is_active_run_status(status: str | None) -> bool:
    return normalize_run_status(status) in ACTIVE_RUN_STATUSES


def is_resumable_run_status(status: str | None) -> bool:
    return normalize_run_status(status) in RESUMABLE_RUN_STATUSES


def is_terminal_run_status(status: str | None) -> bool:
    return normalize_run_status(status) in TERMINAL_RUN_STATUSES
