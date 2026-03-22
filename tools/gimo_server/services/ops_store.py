from __future__ import annotations

import json
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock

from ..config import OPS_DATA_DIR
from ..ops_models import OpsConfig, OpsPlan, OpsRun, RunEvent


logger = logging.getLogger("orchestrator.ops_store")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


class OpsStore:
    """File-backed storage service for OPS data.
    
    Ported from legacy OpsService. Handles CRUD for drafts, runs, plans, and config,
    as well as file-based locking.
    """

    OPS_DIR = OPS_DATA_DIR
    PLAN_FILE = OPS_DIR / "plan.json"
    DRAFTS_DIR = OPS_DIR / "drafts"
    APPROVED_DIR = OPS_DIR / "approved"
    RUNS_DIR = OPS_DIR / "runs"
    RUN_EVENTS_DIR = OPS_DIR / "run_events"
    RUN_LOGS_DIR = OPS_DIR / "run_logs"
    LOCKS_DIR = OPS_DIR / "locks"
    CONFIG_FILE = OPS_DIR / "config.json"
    LOCK_FILE = OPS_DIR / ".ops.lock"

    _RUN_GLOB = "r_*.json"
    _DRAFT_GLOB = "d_*.json"
    _APPROVED_GLOB = "a_*.json"
    _RUN_LOG_TAIL = 200

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
    def record_run_event(cls, run_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """Appends an execution event to the run's journal."""
        entry = RunEvent(event=event_type, data=data)
        path = cls._run_events_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(entry.model_dump_json() + "\n")

    @classmethod
    def read_run_events(cls, run_id: str) -> List[RunEvent]:
        path = cls._run_events_path(run_id)
        if not path.exists():
            return []
        events: List[RunEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(RunEvent.model_validate_json(line))
            except Exception:
                continue
        return events

    @classmethod
    def append_run_log(cls, run_id: str, level: str, msg: str) -> Dict[str, Any]:
        entry = {"ts": _utcnow().isoformat(), "level": level, "msg": msg}
        log_path = cls._run_log_path(run_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    @classmethod
    def read_run_logs(cls, run_id: str, tail: int | None = None) -> List[Dict[str, Any]]:
        log_path = cls._run_log_path(run_id)
        if not log_path.exists():
            return []
        entries: List[Dict[str, Any]] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    entries.append(parsed)
            except Exception:
                continue
        if tail and tail > 0:
            return entries[-tail:]
        return entries

    @classmethod
    def persist_run_metadata(cls, run: OpsRun) -> None:
        payload = run.model_dump(mode="json")
        payload["log"] = [] # Don't persist full logs in metadata file
        cls._run_path(run.id).write_text(_json_dump(payload), encoding="utf-8")

    @classmethod
    def load_run_metadata(cls, run_id: str) -> Optional[OpsRun]:
        f = cls._run_path(run_id)
        if not f.exists():
            return None
        return OpsRun.model_validate_json(f.read_text(encoding="utf-8"))

    @classmethod
    def get_config(cls) -> OpsConfig:
        if cls.CONFIG_FILE.exists():
            try:
                return OpsConfig.model_validate_json(cls.CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error("Failed to load ops config: %s", exc)
        return OpsConfig()

    @classmethod
    def set_config(cls, config: OpsConfig) -> OpsConfig:
        cls.ensure_dirs()
        cls.CONFIG_FILE.write_text(config.model_dump_json(indent=2), encoding="utf-8")
        return config

    @classmethod
    def get_plan(cls) -> Optional[OpsPlan]:
        if cls.PLAN_FILE.exists():
            try:
                return OpsPlan.model_validate_json(cls.PLAN_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error("Failed to load ops plan: %s", exc)
        return None

    @classmethod
    def set_plan(cls, plan: OpsPlan) -> None:
        cls.ensure_dirs()
        cls.PLAN_FILE.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    # --- Locking ---

    @classmethod
    def _merge_lock_path(cls, repo_id: str) -> Path:
        safe_repo_id = str(repo_id or "default")
        digest = hashlib.sha256(safe_repo_id.encode("utf-8", errors="ignore")).hexdigest()[:24]
        return cls.LOCKS_DIR / f"merge_{digest}.json"

    @classmethod
    def acquire_merge_lock(cls, repo_id: str, run_id: str, ttl_seconds: int = 120) -> Dict[str, Any]:
        lock_path = cls._merge_lock_path(repo_id)
        expires_at = _utcnow() + timedelta(seconds=ttl_seconds)
        with cls._lock():
            if lock_path.exists():
                try:
                    data = json.loads(lock_path.read_text(encoding="utf-8"))
                    expires_str = str(data.get("expires_at") or "")
                    if expires_str:
                        expires = datetime.fromisoformat(expires_str)
                        if _utcnow() <= expires:
                            raise RuntimeError(f"Merge lock held by run={data.get('run_id')} until {expires_str}")
                except RuntimeError:
                    raise
                except Exception:
                    pass
            lock_id = f"lock_{os.urandom(4).hex()}"
            payload = {
                "lock_id": lock_id,
                "run_id": run_id,
                "repo_id": repo_id,
                "expires_at": expires_at.isoformat(),
            }
            lock_path.write_text(_json_dump(payload), encoding="utf-8")
        return payload

    @classmethod
    def release_merge_lock(cls, repo_id: str, run_id: str) -> None:
        lock_path = cls._merge_lock_path(repo_id)
        if not lock_path.exists():
            return
        try:
            with cls._lock():
                data = json.loads(lock_path.read_text(encoding="utf-8"))
                if data.get("run_id") == run_id:
                    lock_path.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("release_merge_lock error for repo=%s: %s", repo_id, exc)

    @classmethod
    def heartbeat_merge_lock(cls, repo_id: str, run_id: str, ttl_seconds: int = 120) -> None:
        lock_path = cls._merge_lock_path(repo_id)
        if not lock_path.exists():
            raise RuntimeError(f"No merge lock found for repo={repo_id}")
        with cls._lock():
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            if data.get("run_id") != run_id:
                raise RuntimeError(f"Merge lock held by run={data.get('run_id')}, not {run_id}")
            data["expires_at"] = (_utcnow() + timedelta(seconds=ttl_seconds)).isoformat()
            lock_path.write_text(_json_dump(data), encoding="utf-8")
