from __future__ import annotations

import json
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from filelock import FileLock

from ...config import OPS_DATA_DIR
from ...ops_models import OpsApproved, OpsRun
from ..gics_service import GicsService
from ..agent_telemetry_service import AgentTelemetryService
from ..agent_insight_service import AgentInsightService

logger = logging.getLogger("orchestrator.ops")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


class OpsServiceBase:
    """File-backed OPS storage service.

    Data lives in `.orch_data/ops` under repo base dir.
    """

    OPS_DIR = OPS_DATA_DIR
    PLAN_FILE = OPS_DIR / "plan.json"
    PROVIDER_FILE = OPS_DIR / "provider.json"
    DRAFTS_DIR = OPS_DIR / "drafts"
    APPROVED_DIR = OPS_DIR / "approved"
    RUNS_DIR = OPS_DIR / "runs"
    RUN_EVENTS_DIR = OPS_DIR / "run_events"
    RUN_LOGS_DIR = OPS_DIR / "run_logs"
    LOCKS_DIR = OPS_DIR / "locks"

    CONFIG_FILE = OPS_DIR / "config.json"
    LOCK_FILE = OPS_DIR / ".ops.lock"

    _RUN_GLOB = "*.json"  # matches both r_* and legacy run_* ids
    _DRAFT_GLOB = "d_*.json"
    _APPROVED_GLOB = "a_*.json"
    _RUN_LOG_TAIL = 200
    _ACTIVE_RUN_STATUSES = {"pending", "running", "awaiting_subagents", "MERGE_LOCKED", "WORKER_CRASHED_RECOVERABLE", "AWAITING_MERGE"}
    _TERMINAL_RUN_STATUSES = {"done", "error", "cancelled", "ROLLBACK_EXECUTED", "RISK_SCORE_TOO_HIGH", "BASELINE_TAMPER_DETECTED", "PIPELINE_TIMEOUT", "WORKTREE_CORRUPTED"}

    VALID_TRANSITIONS: Dict[str, set[str]] = {
        # NOTE: keep compatibility with legacy worker paths that may finalize directly from
        # pending when execution starts and completes (or fails) in a single service hop.
        "pending": {
            "running", "cancelled", "error", "awaiting_subagents", "awaiting_review",
            "MERGE_LOCKED", "MERGE_CONFLICT", "VALIDATION_FAILED_TESTS",
            "VALIDATION_FAILED_LINT", "RISK_SCORE_TOO_HIGH", "BASELINE_TAMPER_DETECTED",
            "PIPELINE_TIMEOUT", "WORKTREE_CORRUPTED", "ROLLBACK_EXECUTED",
            "WORKER_CRASHED_RECOVERABLE", "HUMAN_APPROVAL_REQUIRED", "done"
        },
        "running": {
            "done", "error", "cancelled", "awaiting_subagents", "awaiting_review",
            "MERGE_LOCKED", "MERGE_CONFLICT", "VALIDATION_FAILED_TESTS",
            "VALIDATION_FAILED_LINT", "RISK_SCORE_TOO_HIGH", "BASELINE_TAMPER_DETECTED",
            "PIPELINE_TIMEOUT", "WORKTREE_CORRUPTED", "ROLLBACK_EXECUTED",
            "WORKER_CRASHED_RECOVERABLE", "HUMAN_APPROVAL_REQUIRED", "AWAITING_MERGE"
        },
        # awaiting_review: ReviewGate is waiting for orchestrator GO/NO-GO.
        # GO  → running (pipeline continues to done)
        # NO-GO → pending (re-queue with feedback for retry)
        # timeout/error → error
        "awaiting_review": {"running", "pending", "error", "cancelled"},
        "awaiting_subagents": {"running", "error", "cancelled"},
        "MERGE_LOCKED": {"running", "error", "cancelled", "MERGE_CONFLICT"},
        "MERGE_CONFLICT": {"pending", "error", "cancelled"},
        "HUMAN_APPROVAL_REQUIRED": {"running", "cancelled", "error"},
        "AWAITING_MERGE": {"done", "error", "cancelled", "ROLLBACK_EXECUTED", "WORKER_CRASHED_RECOVERABLE"},
        "WORKER_CRASHED_RECOVERABLE": {"pending", "error", "cancelled"},
    }

    _gics: Optional[GicsService] = None
    _telemetry: Optional[AgentTelemetryService] = None
    _insights: Optional[AgentInsightService] = None

    @classmethod
    def ensure_dirs(cls) -> None:
        cls.OPS_DIR.mkdir(parents=True, exist_ok=True)
        cls.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        cls.APPROVED_DIR.mkdir(parents=True, exist_ok=True)
        cls.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        cls.RUN_EVENTS_DIR.mkdir(parents=True, exist_ok=True)
        cls.RUN_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOCKS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _lock(cls) -> FileLock:
        cls.ensure_dirs()
        return FileLock(str(cls.LOCK_FILE))

    @classmethod
    def _draft_path(cls, draft_id: str) -> Path:
        return cls.DRAFTS_DIR / f"{draft_id}.json"

    @classmethod
    def _approved_path(cls, approved_id: str) -> Path:
        return cls.APPROVED_DIR / f"{approved_id}.json"

    @classmethod
    def _run_path(cls, run_id: str) -> Path:
        return cls.RUNS_DIR / f"{run_id}.json"

    @classmethod
    def _run_log_path(cls, run_id: str) -> Path:
        return cls.RUN_LOGS_DIR / f"{run_id}.jsonl"

    @classmethod
    def _run_events_path(cls, run_id: str) -> Path:
        return cls.RUN_EVENTS_DIR / f"{run_id}.jsonl"

    @classmethod
    def _merge_lock_path(cls, repo_id: str) -> Path:
        safe_repo_id = str(repo_id or "default")
        digest = hashlib.sha256(safe_repo_id.encode("utf-8", errors="ignore")).hexdigest()[:24]
        return cls.LOCKS_DIR / f"merge_{digest}.json"

    @classmethod
    def _deterministic_run_id(cls, draft_id: str, commit_base: str) -> str:
        key = f"{draft_id}:{commit_base}"
        digest = hashlib.sha256(key.encode("utf-8", errors="ignore")).hexdigest()[:24]
        return f"r_{digest}"

    @classmethod
    def _new_run_id(cls) -> str:
        return f"r_{int(time.time() * 1000)}_{os.urandom(3).hex()}"

    @classmethod
    def _find_latest_approved_for_draft(cls, draft_id: str) -> Optional[OpsApproved]:
        matches = [item for item in cls.list_approved() if item.draft_id == draft_id]
        if not matches:
            return None
        return max(matches, key=lambda item: item.approved_at)

    @classmethod
    def _find_runs_by_run_key(cls, run_key: str) -> list[OpsRun]:
        if not cls.RUNS_DIR.exists():
            return []
        out: list[OpsRun] = []
        for f in cls.RUNS_DIR.glob(cls._RUN_GLOB):
            try:
                run = OpsRun.model_validate_json(f.read_text(encoding="utf-8"))
                run = cls._materialize_run(run)
                if str(run.run_key or "") == run_key:
                    out.append(run)
            except Exception:
                continue
        return sorted(out, key=lambda r: r.created_at, reverse=True)

    @classmethod
    def _is_run_active(cls, run: OpsRun) -> bool:
        return str(run.status or "") in cls._ACTIVE_RUN_STATUSES
