from __future__ import annotations

import json
import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock

from ..config import OPS_DATA_DIR, OPS_RUN_TTL
from ..ops_models import OpsApproved, OpsConfig, OpsDraft, OpsPlan, OpsRun, AgentInsight
from .gics_service import GicsService
from .agent_telemetry_service import AgentTelemetryService
from .agent_insight_service import AgentInsightService

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
    LOCKS_DIR = OPS_DIR / "locks"

    CONFIG_FILE = OPS_DIR / "config.json"
    LOCK_FILE = OPS_DIR / ".ops.lock"

    _RUN_GLOB = "r_*.json"
    _DRAFT_GLOB = "d_*.json"
    _APPROVED_GLOB = "a_*.json"
    
    _gics: Optional[GicsService] = None
    _telemetry: Optional[AgentTelemetryService] = None
    _insights: Optional[AgentInsightService] = None

    @classmethod
    def set_gics(cls, gics: Optional[GicsService]) -> None:
        cls._gics = gics
        if gics:
            cls._telemetry = AgentTelemetryService(gics)
            cls._insights = AgentInsightService(cls._telemetry)
        else:
            cls._telemetry = None
            cls._insights = None

    @classmethod
    def record_agent_event(cls, event: Any) -> None:
        """Record an agent action event (IDS)."""
        if not cls._telemetry:
            return
        try:
            from ..ops_models import AgentActionEvent
            if not isinstance(event, AgentActionEvent):
                event = AgentActionEvent(**event)
            cls._telemetry.record_event(event)
        except Exception as e:
            logger.error("Failed to record agent event via OpsService: %s", e)

    @classmethod
    def get_agent_insights(cls, agent_id: Optional[str] = None) -> List[AgentInsight]:
        """Get structural recommendations for agent governance."""
        if not cls._insights:
            return []
        return cls._insights.get_recommendations(agent_id=agent_id)

    @classmethod
    def seed_model_priors(
        cls,
        *,
        provider_type: str,
        model_id: str,
        prior_scores: Dict[str, float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Best-effort bridge to GICS for model prior seeding."""
        if not cls._gics:
            return None
        try:
            return cls._gics.seed_model_prior(
                provider_type=provider_type,
                model_id=model_id,
                prior_scores=prior_scores,
                metadata=metadata,
            )
        except Exception:
            return None

    @classmethod
    def record_model_outcome(
        cls,
        *,
        provider_type: str,
        model_id: str,
        success: bool,
        latency_ms: Optional[float] = None,
        cost_usd: Optional[float] = None,
        task_type: str = "general",
    ) -> Optional[Dict[str, Any]]:
        """Best-effort bridge to GICS for post-task model evidence."""
        if not cls._gics:
            return None
        try:
            return cls._gics.record_model_outcome(
                provider_type=provider_type,
                model_id=model_id,
                success=success,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                task_type=task_type,
            )
        except Exception:
            return None

    @classmethod
    def get_model_reliability(cls, *, provider_type: str, model_id: str) -> Optional[Dict[str, Any]]:
        if not cls._gics:
            return None
        try:
            return cls._gics.get_model_reliability(provider_type=provider_type, model_id=model_id)
        except Exception:
            return None

    @classmethod
    def ensure_dirs(cls) -> None:
        cls.OPS_DIR.mkdir(parents=True, exist_ok=True)
        cls.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        cls.APPROVED_DIR.mkdir(parents=True, exist_ok=True)
        cls.RUNS_DIR.mkdir(parents=True, exist_ok=True)
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
    def _merge_lock_path(cls, repo_id: str) -> Path:
        safe_repo_id = str(repo_id or "default")
        digest = hashlib.sha256(safe_repo_id.encode("utf-8", errors="ignore")).hexdigest()[:24]
        return cls.LOCKS_DIR / f"merge_{digest}.json"

    @classmethod
    def _deterministic_run_id(cls, draft_id: str, commit_base: str) -> str:
        key = f"{draft_id}:{commit_base}"
        digest = hashlib.sha256(key.encode("utf-8", errors="ignore")).hexdigest()[:24]
        return f"r_{digest}"

    # -----------------
    # Plan
    # -----------------

    @classmethod
    def get_plan(cls) -> Optional[OpsPlan]:
        # 1. Try local cache
        if cls.PLAN_FILE.exists():
            try:
                return OpsPlan.model_validate_json(cls.PLAN_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error("Failed to load ops plan: %s", exc)
        
        # 2. Try GICS (SSOT)
        if cls._gics:
            try:
                result = cls._gics.get("ops:plan")
                if result and "fields" in result:
                    return OpsPlan.model_validate(result["fields"])
            except Exception as e:
                logger.error("Failed to fallback to GICS for ops plan: %s", e)
        
        return None

    @classmethod
    def set_plan(cls, plan: OpsPlan) -> None:
        cls.ensure_dirs()
        cls.PLAN_FILE.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        if cls._gics:
            try:
                cls._gics.put("ops:plan", plan.model_dump())
            except Exception as e:
                logger.error("Failed to push ops plan to GICS: %s", e)

    # -----------------
    # Config
    # -----------------

    @classmethod
    def get_config(cls) -> OpsConfig:
        # 1. Try local cache
        if cls.CONFIG_FILE.exists():
            try:
                return OpsConfig.model_validate_json(cls.CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error("Failed to load ops config: %s", exc)
        
        # 2. Try GICS (SSOT)
        if cls._gics:
            try:
                result = cls._gics.get("ops:config")
                if result and "fields" in result:
                    return OpsConfig.model_validate(result["fields"])
            except Exception as e:
                logger.error("Failed to fallback to GICS for ops config: %s", e)
        
        return OpsConfig()

    @classmethod
    def set_config(cls, config: OpsConfig) -> OpsConfig:
        cls.ensure_dirs()
        cls.CONFIG_FILE.write_text(config.model_dump_json(indent=2), encoding="utf-8")
        if cls._gics:
            try:
                cls._gics.put("ops:config", config.model_dump())
            except Exception as e:
                logger.error("Failed to push ops config to GICS: %s", e)
        return config

    # -----------------
    # Drafts
    # -----------------

    @classmethod
    def list_drafts(
        cls,
        *,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[OpsDraft]:
        if not cls.DRAFTS_DIR.exists():
            return []
        out: List[OpsDraft] = []
        for f in cls.DRAFTS_DIR.glob(cls._DRAFT_GLOB):
            try:
                draft = OpsDraft.model_validate_json(f.read_text(encoding="utf-8"))
                if status and draft.status != status:
                    continue
                out.append(draft)
            except Exception as exc:
                logger.warning("Failed to parse draft %s: %s", f.name, exc)
        sorted_drafts = sorted(out, key=lambda d: d.created_at, reverse=True)
        if offset is not None:
            sorted_drafts = sorted_drafts[offset:]
        if limit is not None:
            sorted_drafts = sorted_drafts[:limit]
        return sorted_drafts

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
        if cls._gics:
            try:
                cls._gics.put(f"ops:draft:{draft.id}", draft.model_dump())
            except Exception as e:
                logger.error("Failed to push draft %s to GICS: %s", draft.id, e)
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
            
            if cls._gics:
                 try:
                     cls._gics.put(f"ops:approved:{approved.id}", approved.model_dump())
                     cls._gics.put(f"ops:draft:{draft.id}", draft.model_dump())
                 except Exception as e:
                     logger.error("Failed to push approved %s to GICS: %s", approved.id, e)
            return approved

    # -----------------
    # Approved
    # -----------------

    @classmethod
    def list_approved(cls) -> List[OpsApproved]:
        if not cls.APPROVED_DIR.exists():
            return []
        out: List[OpsApproved] = []
        for f in cls.APPROVED_DIR.glob(cls._APPROVED_GLOB):
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
        for f in cls.RUNS_DIR.glob(cls._RUN_GLOB):
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

            draft = cls.get_draft(approved.draft_id)
            context = dict((draft.context if draft else {}) or {})
            repo_context = dict(context.get("repo_context") or {})
            repo_id = str(repo_context.get("repo_id") or repo_context.get("target_branch") or "default")
            commit_base = str(context.get("commit_base") or "HEAD")
            run_id = cls._deterministic_run_id(approved.draft_id, commit_base)

            existing = cls.get_run(run_id)
            if existing:
                return existing

            run = OpsRun(
                id=run_id,
                approved_id=approved_id,
                status="pending",  # type: ignore[arg-type]
                repo_id=repo_id,
                draft_id=approved.draft_id,
                commit_base=commit_base,
                run_key=run_id,
                risk_score=float(context.get("risk_score") or 0.0),
                policy_decision_id=str(context.get("policy_decision_id") or ""),
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
    def set_run_stage(cls, run_id: str, stage: str, *, msg: str | None = None) -> OpsRun:
        with cls._lock():
            run = cls.get_run(run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")
            run.stage = stage
            if msg:
                run.log.append({"ts": _utcnow().isoformat(), "level": "INFO", "msg": msg})
            cls._run_path(run.id).write_text(run.model_dump_json(indent=2), encoding="utf-8")
            return run

    @classmethod
    def update_run_merge_metadata(
        cls,
        run_id: str,
        *,
        commit_before: Optional[str] = None,
        commit_after: Optional[str] = None,
        lock_id: Optional[str] = None,
        lock_expires_at: Optional[datetime] = None,
        heartbeat_at: Optional[datetime] = None,
    ) -> OpsRun:
        with cls._lock():
            run = cls.get_run(run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")
            if commit_before is not None:
                run.commit_before = commit_before
            if commit_after is not None:
                run.commit_after = commit_after
            if lock_id is not None:
                run.lock_id = lock_id
            if lock_expires_at is not None:
                run.lock_expires_at = lock_expires_at
            if heartbeat_at is not None:
                run.heartbeat_at = heartbeat_at
            cls._run_path(run.id).write_text(run.model_dump_json(indent=2), encoding="utf-8")
            return run

    @classmethod
    def acquire_merge_lock(cls, repo_id: str, run_id: str, *, ttl_seconds: int = 120) -> Dict[str, Any]:
        now = _utcnow()
        expires_at = now + timedelta(seconds=max(1, int(ttl_seconds)))
        lock_id = f"ml_{int(time.time() * 1000)}_{os.urandom(2).hex()}"
        lock_payload = {
            "lock_id": lock_id,
            "repo_id": repo_id,
            "run_id": run_id,
            "acquired_at": now.isoformat(),
            "heartbeat_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "ttl_seconds": max(1, int(ttl_seconds)),
        }
        with cls._lock():
            lock_file = cls._merge_lock_path(repo_id)
            if lock_file.exists():
                try:
                    current = json.loads(lock_file.read_text(encoding="utf-8"))
                except Exception:
                    current = {}
                current_expiry = str(current.get("expires_at") or "")
                stale = True
                if current_expiry:
                    try:
                        stale = datetime.fromisoformat(current_expiry) <= now
                    except Exception:
                        stale = True
                if not stale and str(current.get("run_id") or "") != run_id:
                    raise RuntimeError("MERGE_LOCKED")
            lock_file.write_text(_json_dump(lock_payload), encoding="utf-8")
            run = cls.get_run(run_id)
            if run:
                run.lock_id = lock_id
                run.lock_expires_at = expires_at
                run.heartbeat_at = now
                cls._run_path(run.id).write_text(run.model_dump_json(indent=2), encoding="utf-8")
            return lock_payload

    @classmethod
    def heartbeat_merge_lock(cls, repo_id: str, run_id: str, *, ttl_seconds: int = 120) -> Dict[str, Any]:
        now = _utcnow()
        expires_at = now + timedelta(seconds=max(1, int(ttl_seconds)))
        with cls._lock():
            lock_file = cls._merge_lock_path(repo_id)
            if not lock_file.exists():
                raise RuntimeError("MERGE_LOCKED")
            payload = json.loads(lock_file.read_text(encoding="utf-8"))
            if str(payload.get("run_id") or "") != run_id:
                raise RuntimeError("MERGE_LOCKED")
            payload["heartbeat_at"] = now.isoformat()
            payload["expires_at"] = expires_at.isoformat()
            payload["ttl_seconds"] = max(1, int(ttl_seconds))
            lock_file.write_text(_json_dump(payload), encoding="utf-8")
            run = cls.get_run(run_id)
            if run:
                run.lock_expires_at = expires_at
                run.heartbeat_at = now
                cls._run_path(run.id).write_text(run.model_dump_json(indent=2), encoding="utf-8")
            return payload

    @classmethod
    def release_merge_lock(cls, repo_id: str, run_id: str) -> bool:
        with cls._lock():
            lock_file = cls._merge_lock_path(repo_id)
            if not lock_file.exists():
                return False
            try:
                payload = json.loads(lock_file.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            if str(payload.get("run_id") or "") != run_id:
                return False
            lock_file.unlink(missing_ok=True)
            return True

    @classmethod
    def recover_stale_lock(cls, repo_id: str) -> bool:
        now = _utcnow()
        with cls._lock():
            lock_file = cls._merge_lock_path(repo_id)
            if not lock_file.exists():
                return False
            try:
                payload = json.loads(lock_file.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(str(payload.get("expires_at") or ""))
            except Exception:
                lock_file.unlink(missing_ok=True)
                return True
            if expires_at <= now:
                lock_file.unlink(missing_ok=True)
                return True
            return False

    @classmethod
    def _extract_strategy_fields(cls, run: Any) -> Dict[str, str]:
        strategy_line = ""
        for entry in reversed(run.log or []):
            msg = str((entry or {}).get("msg") or "")
            if msg.startswith("Model strategy:"):
                strategy_line = msg
                break

        strategy_fields: Dict[str, str] = {}
        if strategy_line:
            payload = strategy_line.replace("Model strategy:", "").strip()
            for part in payload.split(" "):
                if "=" in part:
                    k, v = part.split("=", 1)
                    strategy_fields[k.strip()] = v.strip()
        return strategy_fields

    @classmethod
    def _extract_hashes(cls, context: dict, approved: Any, content: str) -> tuple[str, str]:
        expected = str(context.get("policy_hash_expected") or "")
        runtime = str(context.get("policy_hash_runtime") or "")
        if not expected:
            expected = hashlib.sha256((approved.prompt or "").encode("utf-8", errors="ignore")).hexdigest()
        if not runtime:
            runtime = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
        return expected, runtime

    @classmethod
    def _c_str(cls, ctx: dict, k1: str, k2: str = None, def_val: str = "") -> str:
        v = ctx.get(k1)
        if not v and k2:
            v = ctx.get(k2)
        return str(v or def_val)

    @classmethod
    def _build_preview_dict(
        cls,
        run,
        approved,
        context: dict,
        strategy_fields: dict,
        expected: str,
        runtime: str,
        request_id: Optional[str],
        trace_id: Optional[str]
    ) -> Dict[str, Any]:
        content = approved.content or ""
        diff_summary = context.get("diff_summary") or f"content_chars={len(content)}"
        model_used = cls._c_str(context, "model_used", def_val=approved.provider or "unknown")

        fallback_used = bool(
            str(context.get("fallback_used", strategy_fields.get("fallback_used", False))).lower() in {"1", "true", "yes"}
        )

        return {
            "run_id": run.id,
            "draft_id": approved.draft_id,
            "status": run.status,
            "final_status": run.status,
            "diff_summary": diff_summary,
            "risk_score": float(context.get("risk_score", 0.0) or 0.0),
            "intent_declared": cls._c_str(context, "intent_declared", "intent_class"),
            "intent_effective": cls._c_str(context, "intent_effective", "intent_class"),
            "decision_reason": cls._c_str(context, "decision_reason"),
            "execution_decision": cls._c_str(context, "execution_decision"),
            "model_used": model_used,
            "model_attempted": cls._c_str(context, "model_attempted", def_val=strategy_fields.get("attempted") or ""),
            "failure_reason": cls._c_str(context, "failure_reason", def_val=strategy_fields.get("failure_reason") or ""),
            "final_model_used": cls._c_str(context, "final_model_used", def_val=strategy_fields.get("final_model") or model_used),
            "fallback_used": fallback_used,
            "policy_decision_id": cls._c_str(context, "policy_decision_id"),
            "policy_decision": cls._c_str(context, "policy_decision"),
            "policy_status_code": cls._c_str(context, "policy_status_code"),
            "policy_triggered_rules": list(context.get("policy_triggered_rules") or []),
            "policy_hash_expected": expected,
            "policy_hash_runtime": runtime,
            "baseline_version": cls._c_str(context, "baseline_version", def_val="v1"),
            "commit_before": cls._c_str(context, "commit_before", def_val=run.commit_before or "unknown"),
            "commit_after": cls._c_str(context, "commit_after", def_val=run.commit_after or "unknown"),
            "trace_id": str(trace_id or context.get("trace_id") or ""),
            "request_id": str(request_id or context.get("request_id") or ""),
            "updated_at": _utcnow().isoformat(),
        }

    @classmethod
    def get_run_preview(
        cls,
        run_id: str,
        *,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return a stable preview payload for audit/UI contracts."""
        run = cls.get_run(run_id)
        if not run:
            return None
        approved = cls.get_approved(run.approved_id)
        if not approved:
            return None
        draft = cls.get_draft(approved.draft_id)
        context = dict((draft.context if draft else {}) or {})

        content = approved.content or ""
        expected, runtime = cls._extract_hashes(context, approved, content)
        strategy_fields = cls._extract_strategy_fields(run)

        return cls._build_preview_dict(
            run, approved, context, strategy_fields, expected, runtime, request_id, trace_id
        )

    @classmethod
    def get_runs_by_status(cls, status: str) -> List[OpsRun]:
        if not cls.RUNS_DIR.exists():
            return []
        out: List[OpsRun] = []
        for f in cls.RUNS_DIR.glob(cls._RUN_GLOB):
            try:
                run = OpsRun.model_validate_json(f.read_text(encoding="utf-8"))
                if run.status == status:
                    out.append(run)
            except Exception:
                continue
        return sorted(out, key=lambda r: r.created_at)

    @classmethod
    def count_active_runs(cls) -> int:
        if not cls.RUNS_DIR.exists():
            return 0
        count = 0
        for f in cls.RUNS_DIR.glob(cls._RUN_GLOB):
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
        for f in cls.RUNS_DIR.glob(cls._RUN_GLOB):
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
        for f in cls.DRAFTS_DIR.glob(cls._DRAFT_GLOB):
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
        for f in cls.RUNS_DIR.glob(cls._RUN_GLOB):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    f.unlink(missing_ok=True)
                    cleaned += 1
            except Exception:
                continue
        return cleaned
