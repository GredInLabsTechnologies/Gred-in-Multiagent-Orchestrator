from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock

from ..config import OPS_DATA_DIR, OPS_RUN_TTL
from ..ops_models import OpsApproved, OpsConfig, OpsDraft, OpsPlan, OpsRun

logger = logging.getLogger("orchestrator.ops")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


class OpsService:
    """File-backed OPS storage service.

    Data lives in `.orch_data/ops` under repo base dir.
    """

    OPS_DIR = OPS_DATA_DIR
    PLAN_FILE = OPS_DIR / "plan.json"
    PROVIDER_FILE = OPS_DIR / "provider.json"
    DRAFTS_DIR = OPS_DIR / "drafts"
    APPROVED_DIR = OPS_DIR / "approved"
    RUNS_DIR = OPS_DIR / "runs"

    CONFIG_FILE = OPS_DIR / "config.json"
    LOCK_FILE = OPS_DIR / ".ops.lock"

    @classmethod
    def ensure_dirs(cls) -> None:
        cls.OPS_DIR.mkdir(parents=True, exist_ok=True)
        cls.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        cls.APPROVED_DIR.mkdir(parents=True, exist_ok=True)
        cls.RUNS_DIR.mkdir(parents=True, exist_ok=True)

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

    # -----------------
    # Plan
    # -----------------

    @classmethod
    def get_plan(cls) -> Optional[OpsPlan]:
        if not cls.PLAN_FILE.exists():
            return None
        try:
            return OpsPlan.model_validate_json(cls.PLAN_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load ops plan: %s", exc)
            return None

    @classmethod
    def set_plan(cls, plan: OpsPlan) -> None:
        cls.ensure_dirs()
        cls.PLAN_FILE.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    # -----------------
    # Config
    # -----------------

    @classmethod
    def get_config(cls) -> OpsConfig:
        if not cls.CONFIG_FILE.exists():
            return OpsConfig()
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

    # -----------------
    # Drafts
    # -----------------

    @classmethod
    def list_drafts(cls) -> List[OpsDraft]:
        if not cls.DRAFTS_DIR.exists():
            return []
        out: List[OpsDraft] = []
        for f in cls.DRAFTS_DIR.glob("d_*.json"):
            try:
                out.append(OpsDraft.model_validate_json(f.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.warning("Failed to parse draft %s: %s", f.name, exc)
        return sorted(out, key=lambda d: d.created_at, reverse=True)

    @classmethod
    def create_draft(
        cls,
        prompt: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        provider: Optional[str] = None,
        content: Optional[str] = None,
        status: str = "draft",
        error: Optional[str] = None,
    ) -> OpsDraft:
        cls.ensure_dirs()
        draft_id = f"d_{int(time.time() * 1000)}_{os.urandom(3).hex()}"
        draft = OpsDraft(
            id=draft_id,
            prompt=prompt,
            context=context or {},
            provider=provider,
            content=content,
            status=status,  # type: ignore[arg-type]
            error=error,
            created_at=_utcnow(),
        )
        cls._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
        return draft

    @classmethod
    def get_draft(cls, draft_id: str) -> Optional[OpsDraft]:
        f = cls._draft_path(draft_id)
        if not f.exists():
            return None
        return OpsDraft.model_validate_json(f.read_text(encoding="utf-8"))

    @classmethod
    def update_draft(cls, draft_id: str, *, prompt: Optional[str], content: Optional[str], context: Optional[Dict[str, Any]]) -> OpsDraft:
        with cls._lock():
            draft = cls.get_draft(draft_id)
            if not draft:
                raise ValueError(f"Draft {draft_id} not found")
            if prompt is not None:
                draft.prompt = prompt
            if content is not None:
                draft.content = content
            if context is not None:
                draft.context = context
            cls._draft_path(draft_id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
            return draft

    @classmethod
    def reject_draft(cls, draft_id: str) -> OpsDraft:
        with cls._lock():
            draft = cls.get_draft(draft_id)
            if not draft:
                raise ValueError(f"Draft {draft_id} not found")
            draft.status = "rejected"  # type: ignore[assignment]
            cls._draft_path(draft_id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
            return draft

    @classmethod
    def approve_draft(cls, draft_id: str, *, approved_by: Optional[str] = None) -> OpsApproved:
        with cls._lock():
            draft = cls.get_draft(draft_id)
            if not draft:
                raise ValueError(f"Draft {draft_id} not found")
            if draft.status == "rejected":
                raise ValueError("Cannot approve a rejected draft")

            approved_id = f"a_{int(time.time() * 1000)}_{os.urandom(3).hex()}"
            approved = OpsApproved(
                id=approved_id,
                draft_id=draft.id,
                prompt=draft.prompt,
                provider=draft.provider,
                content=draft.content or "",
                approved_at=_utcnow(),
                approved_by=approved_by,
            )

            # Atomically move: write approved then mark draft as approved
            cls._approved_path(approved.id).write_text(
                approved.model_dump_json(indent=2), encoding="utf-8"
            )
            draft.status = "approved"  # type: ignore[assignment]
            cls._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
            return approved

    # -----------------
    # Approved
    # -----------------

    @classmethod
    def list_approved(cls) -> List[OpsApproved]:
        if not cls.APPROVED_DIR.exists():
            return []
        out: List[OpsApproved] = []
        for f in cls.APPROVED_DIR.glob("a_*.json"):
            try:
                out.append(OpsApproved.model_validate_json(f.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.warning("Failed to parse approved %s: %s", f.name, exc)
        return sorted(out, key=lambda a: a.approved_at, reverse=True)

    @classmethod
    def get_approved(cls, approved_id: str) -> Optional[OpsApproved]:
        f = cls._approved_path(approved_id)
        if not f.exists():
            return None
        return OpsApproved.model_validate_json(f.read_text(encoding="utf-8"))

    # -----------------
    # Runs
    # -----------------

    @classmethod
    def list_runs(cls) -> List[OpsRun]:
        if not cls.RUNS_DIR.exists():
            return []
        out: List[OpsRun] = []
        for f in cls.RUNS_DIR.glob("r_*.json"):
            try:
                out.append(OpsRun.model_validate_json(f.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.warning("Failed to parse run %s: %s", f.name, exc)
        return sorted(out, key=lambda r: r.created_at, reverse=True)

    @classmethod
    def get_run(cls, run_id: str) -> Optional[OpsRun]:
        f = cls._run_path(run_id)
        if not f.exists():
            return None
        return OpsRun.model_validate_json(f.read_text(encoding="utf-8"))

    @classmethod
    def create_run(cls, approved_id: str) -> OpsRun:
        with cls._lock():
            if approved_id.startswith("d_"):
                raise PermissionError("Runs can only be created from approved_id")
            approved = cls.get_approved(approved_id)
            if not approved:
                raise ValueError(f"Approved entry {approved_id} not found")
            run_id = f"r_{int(time.time() * 1000)}_{os.urandom(3).hex()}"
            run = OpsRun(
                id=run_id,
                approved_id=approved_id,
                status="pending",  # type: ignore[arg-type]
                log=[{"ts": _utcnow().isoformat(), "level": "INFO", "msg": "Run created"}],
                started_at=None,
                created_at=_utcnow(),
            )
            cls._run_path(run.id).write_text(run.model_dump_json(indent=2), encoding="utf-8")
            return run

    @classmethod
    def append_log(cls, run_id: str, *, level: str, msg: str) -> OpsRun:
        with cls._lock():
            run = cls.get_run(run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")
            run.log.append({"ts": _utcnow().isoformat(), "level": level, "msg": msg})
            cls._run_path(run.id).write_text(run.model_dump_json(indent=2), encoding="utf-8")
            return run

    @classmethod
    def update_run_status(cls, run_id: str, status: str, *, msg: str | None = None) -> OpsRun:
        with cls._lock():
            run = cls.get_run(run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")
            run.status = status  # type: ignore[assignment]
            if status == "running" and not run.started_at:
                run.started_at = _utcnow()
            if msg:
                run.log.append({"ts": _utcnow().isoformat(), "level": "INFO", "msg": msg})
            cls._run_path(run.id).write_text(run.model_dump_json(indent=2), encoding="utf-8")
            return run

    @classmethod
    def count_active_runs(cls) -> int:
        if not cls.RUNS_DIR.exists():
            return 0
        count = 0
        for f in cls.RUNS_DIR.glob("r_*.json"):
            try:
                run = OpsRun.model_validate_json(f.read_text(encoding="utf-8"))
                if run.status in ("pending", "running"):
                    count += 1
            except Exception:
                continue
        return count

    @classmethod
    def list_pending_runs(cls) -> List[OpsRun]:
        if not cls.RUNS_DIR.exists():
            return []
        out: List[OpsRun] = []
        for f in cls.RUNS_DIR.glob("r_*.json"):
            try:
                run = OpsRun.model_validate_json(f.read_text(encoding="utf-8"))
                if run.status == "pending":
                    out.append(run)
            except Exception:
                continue
        return sorted(out, key=lambda r: r.created_at)

    @classmethod
    def cleanup_old_drafts(cls) -> int:
        """Remove rejected/error drafts older than config.draft_cleanup_ttl_days."""
        config = cls.get_config()
        ttl_days = config.draft_cleanup_ttl_days
        if ttl_days <= 0 or not cls.DRAFTS_DIR.exists():
            return 0
        now = _utcnow()
        cutoff = now - timedelta(days=ttl_days)
        cleaned = 0
        for f in cls.DRAFTS_DIR.glob("d_*.json"):
            try:
                draft = OpsDraft.model_validate_json(f.read_text(encoding="utf-8"))
                if draft.status in ("rejected", "error") and draft.created_at.replace(tzinfo=timezone.utc) < cutoff:
                    f.unlink(missing_ok=True)
                    cleaned += 1
            except Exception:
                continue
        return cleaned

    @classmethod
    def cleanup_old_runs(cls, *, ttl_seconds: int | None = None) -> int:
        ttl = ttl_seconds if ttl_seconds is not None else OPS_RUN_TTL
        if ttl <= 0:
            return 0
        if not cls.RUNS_DIR.exists():
            return 0

        now = _utcnow()
        cutoff = now - timedelta(seconds=ttl)
        cleaned = 0
        for f in cls.RUNS_DIR.glob("r_*.json"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    f.unlink(missing_ok=True)
                    cleaned += 1
            except Exception:
                continue
        return cleaned
