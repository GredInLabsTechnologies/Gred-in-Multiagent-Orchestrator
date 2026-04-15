from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ...config import OPS_RUN_TTL
from ...ops_models import OpsRun
from ..lifecycle_errors import RunNotFoundError
from ..run_lifecycle import is_resumable_run_status
from ._base import _utcnow, _json_dump

logger = logging.getLogger("orchestrator.ops")


class RunMixin:
    """Run CRUD, event store, log store, and run lifecycle."""

    # --- Event store internals ---

    @classmethod
    def _append_run_event(cls, run_id: str, event: Dict[str, Any]) -> None:
        path = cls._run_events_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    @classmethod
    def _read_run_events(cls, run_id: str) -> List[Dict[str, Any]]:
        path = cls._run_events_path(run_id)
        if not path.exists():
            return []
        events: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    events.append(payload)
            except Exception:
                continue
        return events

    @classmethod
    def _apply_run_event(cls, run: OpsRun, event: Dict[str, Any]) -> None:
        event_type = str(event.get("event") or "")
        data = dict(event.get("data") or {})
        if event_type == "status":
            status = data.get("status")
            if status:
                run.status = status  # type: ignore[assignment]
            if data.get("started_at"):
                try:
                    run.started_at = datetime.fromisoformat(str(data.get("started_at")))
                except Exception:
                    pass
        elif event_type == "stage":
            run.stage = data.get("stage")
        elif event_type == "merge_meta":
            for key, value in data.items():
                if not hasattr(run, key):
                    continue
                if key in {"lock_expires_at", "heartbeat_at", "resume_requested_at"} and value:
                    try:
                        value = datetime.fromisoformat(str(value))
                    except Exception:
                        pass
                setattr(run, key, value)

    @classmethod
    def _materialize_run(cls, run: OpsRun) -> OpsRun:
        for event in cls._read_run_events(run.id):
            cls._apply_run_event(run, event)
        return run

    @classmethod
    def _compact_run_events_if_needed(cls, run: OpsRun) -> None:
        events_path = cls._run_events_path(run.id)
        events = cls._read_run_events(run.id)
        if len(events) < 50:
            return
        cls._persist_run(run)
        events_path.write_text("", encoding="utf-8")

    @classmethod
    def _persist_run(cls, run: OpsRun) -> None:
        payload = run.model_dump(mode="json")
        payload["log"] = []
        cls._run_path(run.id).write_text(_json_dump(payload), encoding="utf-8")

    @classmethod
    def merge_run_meta(cls, run_id: str, *, msg: str | None = None, **fields: Any) -> OpsRun:
        with cls._lock():
            run = cls._load_run_metadata(run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")
            if msg:
                cls._append_run_log_entry(run_id, level="INFO", msg=msg)
            payload = {key: value for key, value in fields.items()}
            if payload:
                cls._append_run_event(
                    run_id,
                    {
                        "ts": _utcnow().isoformat(),
                        "event": "merge_meta",
                        "data": payload,
                    },
                )
            run = cls._materialize_run(run)
            cls._compact_run_events_if_needed(run)
            run.log = cls._read_run_logs(run_id, tail=cls._RUN_LOG_TAIL)
            return run

    # --- Log store internals ---

    @classmethod
    def _append_run_log_entry(cls, run_id: str, *, level: str, msg: str) -> Dict[str, Any]:
        run_key = None
        try:
            # Best effort to get run_key without recursion
            f = cls._run_path(run_id)
            if f.exists():
                data = json.loads(f.read_text(encoding="utf-8"))
                run_key = data.get("run_key")
        except Exception:
            pass

        entry = {
            "ts": _utcnow().isoformat(),
            "level": level,
            "msg": msg,
            "run_key": run_key
        }
        log_path = cls._run_log_path(run_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    @classmethod
    def _read_run_logs(cls, run_id: str, *, tail: int | None = None) -> List[Dict[str, Any]]:
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
    def _load_run_metadata(cls, run_id: str) -> Optional[OpsRun]:
        f = cls._run_path(run_id)
        if not f.exists():
            return None
        return OpsRun.model_validate_json(f.read_text(encoding="utf-8"))

    # --- Run CRUD ---

    @classmethod
    def list_runs(cls) -> List[OpsRun]:
        if not cls.RUNS_DIR.exists():
            return []
        out: List[OpsRun] = []
        for f in cls.RUNS_DIR.glob(cls._RUN_GLOB):
            try:
                run = OpsRun.model_validate_json(f.read_text(encoding="utf-8"))
                run = cls._materialize_run(run)
                run.log = cls._read_run_logs(run.id, tail=cls._RUN_LOG_TAIL)
                out.append(run)
            except Exception as exc:
                logger.warning("Failed to parse run %s: %s", f.name, exc)
        return sorted(out, key=lambda r: r.created_at, reverse=True)

    @classmethod
    def get_run(cls, run_id: str) -> Optional[OpsRun]:
        run = cls._load_run_metadata(run_id)
        if not run:
            return None
        run = cls._materialize_run(run)
        run.log = cls._read_run_logs(run_id, tail=cls._RUN_LOG_TAIL)
        return run

    @classmethod
    def list_pending_runs(cls) -> List[OpsRun]:
        return [r for r in cls.list_runs() if r.status == "pending"]

    @classmethod
    def get_runs_by_status(cls, status: str) -> List[OpsRun]:
        return [r for r in cls.list_runs() if r.status == status]

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
            # R20-001: propagate operator_class from the draft into the stage
            # context so the policy gate / intent classifier can whitelist
            # cognitive_agent operators (MCP, agent SDK) and avoid the
            # "fallback_to_most_restrictive_human_review" branch.
            if draft is not None:
                context["operator_class"] = str(
                    getattr(draft, "operator_class", None) or "human_ui"
                )
            validated_task_spec = dict(context.get("validated_task_spec") or {})
            repo_context = dict(context.get("repo_context") or {})
            repo_context_pack = dict(context.get("repo_context_pack") or {})
            surface = str(context.get("surface") or "operator")
            workspace_mode = str(context.get("workspace_mode") or "ephemeral")
            repo_id = str(repo_context.get("repo_id") or repo_context.get("target_branch") or "default")
            commit_base = str(validated_task_spec.get("base_commit") or context.get("commit_base") or "HEAD")
            run_key = cls._deterministic_run_id(approved.draft_id, commit_base)
            run_id = cls._new_run_id()

            runs_for_key = cls._find_runs_by_run_key(run_key)
            active = next((item for item in runs_for_key if cls._is_run_active(item)), None)

            # STALE RUN RECOVERY: If a run is active but has no heartbeat for > 10 mins, treat it as orphaned
            if active:
                stale_threshold = _utcnow() - timedelta(minutes=10)
                heartbeat = active.heartbeat_at or active.created_at
                if heartbeat < stale_threshold:
                    logger.warning("Recovering stale run %s for run_key %s", active.id, run_key)
                    # Force move to error so it's no longer 'active'
                    cls._append_run_log_entry(active.id, level="ERROR", msg="Marked as STALE by new run attempt")
                    active.status = "error"
                    cls._persist_run(active)
                    active = None # Allow new run

            if active:
                raise RuntimeError(f"RUN_ALREADY_ACTIVE:{active.id}")

            attempt = 1
            if runs_for_key:
                attempt = max(int(item.attempt or 1) for item in runs_for_key) + 1

            if validated_task_spec:
                from ..app_session_service import AppSessionService
                from ..execution.sandbox_service import SandboxService
                from ..workspace.workspace_policy_service import WorkspacePolicyService

                repo_handle = str(validated_task_spec.get("repo_handle") or "").strip()
                if surface == WorkspacePolicyService.SURFACE_CHATGPT_APP:
                    session_id = str(repo_context_pack.get("session_id") or "").strip()
                    repo_path = AppSessionService.get_bound_repo_path(session_id) if session_id else None
                    if not repo_path:
                        raise RuntimeError("CHATGPT_APP_REPO_SNAPSHOT_UNAVAILABLE")
                else:
                    repo_path = AppSessionService.get_path_from_handle(repo_handle) if repo_handle else None
                if not repo_path:
                    raise RuntimeError("VALIDATED_TASK_SPEC_REPO_UNRESOLVABLE")

                effective_mode = WorkspacePolicyService.resolve_effective_mode(
                    requested_mode=workspace_mode,
                    surface=surface,
                )
                validated_task_spec["workspace_mode"] = effective_mode
                if effective_mode == WorkspacePolicyService.MODE_SOURCE_REPO:
                    validated_task_spec["workspace_path"] = str(repo_path)
                else:
                    sandbox = SandboxService.create_worktree_handle(run_id, repo_path, base_ref=commit_base)
                    validated_task_spec["workspace_path"] = str(sandbox.worktree_path)

            # P10: Extract routing metadata before draft expires
            routing_decision_raw = context.get("routing_decision")
            _rd = routing_decision_raw if isinstance(routing_decision_raw, dict) else None
            _rd_profile = (_rd or {}).get("profile") or {}
            agent_preset = (
                context.get("agent_preset")
                or _rd_profile.get("agent_preset")
                or None
            )
            execution_policy_name = (
                context.get("execution_policy_name")
                or _rd_profile.get("execution_policy")
                or None
            )
            routing_snapshot = _rd  # None if absent

            run = OpsRun(
                id=run_id,
                approved_id=approved_id,
                status="pending",  # type: ignore[arg-type]
                repo_id=repo_id,
                draft_id=approved.draft_id,
                commit_base=commit_base,
                run_key=run_key,
                risk_score=float(context.get("risk_score") or 0.0),
                policy_decision_id=str(context.get("policy_decision_id") or ""),
                log=[],
                started_at=None,
                created_at=_utcnow(),
                attempt=attempt,
                validated_task_spec=validated_task_spec or None,
                agent_preset=agent_preset,
                execution_policy_name=execution_policy_name,
                routing_snapshot=routing_snapshot,
            )
            entry = cls._append_run_log_entry(run.id, level="INFO", msg="Run created")
            run.log = [entry]
            cls._persist_run(run)
            cls._append_run_event(
                run.id,
                {
                    "ts": _utcnow().isoformat(),
                    "event": "status",
                    "data": {"status": "pending"},
                },
            )
            try:
                from ..authority import ExecutionAuthority
                ExecutionAuthority.get().run_worker.notify()
            except Exception:
                pass
            return run

    @classmethod
    def rerun(cls, run_id: str) -> OpsRun:
        source = cls.get_run(run_id)
        if not source:
            raise ValueError(f"Run {run_id} not found")

        # Explicit rerun semantics: do not rerun a source run that is still active.
        if cls._is_run_active(source):
            raise RuntimeError(f"RERUN_SOURCE_ACTIVE:{source.id}")

        rerun = cls.create_run(source.approved_id)
        rerun.rerun_of = source.id
        cls._persist_run(rerun)
        return rerun

    @classmethod
    def append_log(cls, run_id: str, *, level: str, msg: str) -> OpsRun:
        with cls._lock():
            run = cls._load_run_metadata(run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")
            cls._append_run_log_entry(run_id, level=level, msg=msg)
            run.log = cls._read_run_logs(run_id, tail=cls._RUN_LOG_TAIL)
            return run

    @classmethod
    def update_run_status(cls, run_id: str, status: str, *, msg: str | None = None) -> OpsRun:
        with cls._lock():
            run = cls._load_run_metadata(run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")

            # FSM Guard — materialize events to get the ACTUAL current state.
            # The base JSON may still show the initial status because non-terminal
            # transitions are stored as events and only compacted after ≥50 events.
            # Reading only the base metadata would give stale status for the guard.
            run_materialized = cls._materialize_run(cls._load_run_metadata(run_id))
            current_status = str(run_materialized.status or "pending")
            if current_status == status:
                return run  # Idempotent

            allowed = cls.VALID_TRANSITIONS.get(current_status, set())
            if status not in allowed:
                # Strictly enforce FSM in production
                raise RuntimeError(f"INVALID_FSM_TRANSITION:{current_status}->{status}")

            started_at = None
            if status == "running" and not run.started_at:
                started_at = _utcnow().isoformat()
            if msg:
                cls._append_run_log_entry(run_id, level="INFO", msg=msg)
            cls._append_run_event(
                run_id,
                {
                    "ts": _utcnow().isoformat(),
                    "event": "status",
                    "data": {"status": status, **({"started_at": started_at} if started_at else {})},
                },
            )
            run = cls._materialize_run(run)
            if status in cls._TERMINAL_RUN_STATUSES:
                cls._persist_run(run)
            else:
                cls._compact_run_events_if_needed(run)
            run.log = cls._read_run_logs(run_id, tail=cls._RUN_LOG_TAIL)
            return run

    @classmethod
    def resume_run(
        cls,
        run_id: str,
        *,
        decision: str = "approve",
        edited_state: Optional[Dict[str, Any]] = None,
    ) -> OpsRun:
        run = cls.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        if not is_resumable_run_status(run.status):
            raise RuntimeError(f"RUN_NOT_RESUMABLE:{run.id}:{run.status}")

        normalized = str(decision or "approve").strip().lower()
        now = _utcnow()
        resume_context = dict(run.resume_context or {})
        if isinstance(edited_state, dict):
            resume_context.update(edited_state)
        resume_context["handover_decision"] = normalized
        resume_context["resume_requested_at"] = now.isoformat()

        if normalized in {"approve", "approved", "resume", "continue"}:
            resume_context["human_approval_granted"] = True
            cls.merge_run_meta(
                run_id,
                msg=f"Handover decision recorded: {normalized}",
                resume_context=resume_context,
                last_handover_decision=normalized,
                resume_requested_at=now.isoformat(),
            )
            resumed = cls.update_run_status(run_id, "pending", msg="Run re-queued after handover approval")
            try:
                from ..authority import ExecutionAuthority

                ExecutionAuthority.get().run_worker.notify()
            except Exception:
                pass
            return resumed

        if normalized in {"reject", "rejected", "deny", "cancel", "cancelled"}:
            cls.merge_run_meta(
                run_id,
                msg=f"Handover decision recorded: {normalized}",
                resume_context=resume_context,
                last_handover_decision=normalized,
                resume_requested_at=now.isoformat(),
            )
            return cls.update_run_status(run_id, "cancelled", msg="Run cancelled after handover rejection")

        raise RuntimeError(f"INVALID_HANDOVER_DECISION:{decision}")

    @classmethod
    def heartbeat_run(cls, run_id: str) -> Optional[OpsRun]:
        """R17 Cluster A: record a wall-clock heartbeat for an executing run.

        Wall-clock UTC is used (not monotonic) because reclamation must work
        across process restarts, where monotonic clocks reset. The
        ``heartbeat_at`` field already exists on ``OpsRun`` and is materialized
        by the existing event store via ``merge_meta`` events.
        Returns None silently if the run is gone (best-effort telemetry).
        """
        try:
            with cls._lock():
                run = cls._load_run_metadata(run_id)
                if not run:
                    return None
                now = _utcnow()
                cls._append_run_event(
                    run_id,
                    {
                        "ts": now.isoformat(),
                        "event": "merge_meta",
                        "data": {"heartbeat_at": now.isoformat()},
                    },
                )
                run = cls._materialize_run(run)
                cls._compact_run_events_if_needed(run)
                return run
        except Exception as exc:
            logger.debug("heartbeat_run failed for %s: %s", run_id, exc)
            return None

    @classmethod
    def set_run_stage(cls, run_id: str, stage: str, *, msg: str | None = None) -> OpsRun:
        with cls._lock():
            run = cls._load_run_metadata(run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")
            cls._append_run_event(
                run_id,
                {
                    "ts": _utcnow().isoformat(),
                    "event": "stage",
                    "data": {"stage": stage},
                },
            )
            if msg:
                cls._append_run_log_entry(run_id, level="INFO", msg=msg)
            run = cls._materialize_run(run)
            cls._compact_run_events_if_needed(run)
            run.log = cls._read_run_logs(run_id, tail=cls._RUN_LOG_TAIL)
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
            run = cls._load_run_metadata(run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")
            cls._append_run_event(
                run_id,
                {
                    "ts": _utcnow().isoformat(),
                    "event": "merge_meta",
                    "data": {
                        **({"commit_before": commit_before} if commit_before is not None else {}),
                        **({"commit_after": commit_after} if commit_after is not None else {}),
                        **({"lock_id": lock_id} if lock_id is not None else {}),
                        **({"lock_expires_at": lock_expires_at.isoformat()} if lock_expires_at is not None else {}),
                        **({"heartbeat_at": heartbeat_at.isoformat()} if heartbeat_at is not None else {}),
                    },
                },
            )
            run = cls._materialize_run(run)
            cls._compact_run_events_if_needed(run)
            run.log = cls._read_run_logs(run_id, tail=cls._RUN_LOG_TAIL)
            return run

    @classmethod
    def get_run_preview(
        cls,
        run_id: str,
        *,
        request_id: str = "",
        trace_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Return a lightweight preview payload for a run (used by observability UI)."""
        run = cls.get_run(run_id)
        if not run:
            return None

        approved = cls.get_approved(run.approved_id) if run.approved_id else None
        draft = cls.get_draft(approved.draft_id) if approved else None
        context = dict((draft.context if draft else {}) or {})

        diff_summary = "No diff summary available"
        log_tail = cls._read_run_logs(run_id, tail=20)
        if log_tail:
            last_msg = str((log_tail[-1] or {}).get("msg") or "").strip()
            if last_msg:
                diff_summary = last_msg[:400]

        model_attempted = str(context.get("model_attempted") or "")
        final_model_used = str(context.get("final_model_used") or "")
        model_used = final_model_used or model_attempted

        return {
            "run_id": run.id,
            "status": run.status,
            "final_status": run.status,
            "stage": run.stage,
            "intent_effective": str(context.get("intent_effective") or ""),
            "repo_id": run.repo_id,
            "baseline_version": str(context.get("baseline_version") or run.commit_base or ""),
            "model_attempted": model_attempted,
            "final_model_used": final_model_used,
            "model_used": model_used,
            "risk_score": float(context.get("risk_score") or run.risk_score or 0.0),
            "policy_hash_expected": str(context.get("policy_hash_expected") or ""),
            "policy_hash_runtime": str(context.get("policy_hash_runtime") or ""),
            "commit_before": run.commit_before,
            "commit_after": run.commit_after,
            "diff_summary": diff_summary,
            "request_id": request_id,
            "trace_id": trace_id,
            "log_tail": log_tail,
        }

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
                    cls._run_log_path(f.stem).unlink(missing_ok=True)
                    cls._run_events_path(f.stem).unlink(missing_ok=True)
                    cleaned += 1
            except Exception:
                continue
        return cleaned

    @classmethod
    def discard_run(cls, run_id: str):
        """Phase 6B: Discard a run manually. Triggers immediate purge."""
        from ..purge_service import PurgeService

        run = cls.get_run(run_id)
        if not run:
            raise RunNotFoundError(f"Run {run_id} not found")

        # Move to cancelled if not terminal
        if run.status not in cls._TERMINAL_RUN_STATUSES:
            cls.update_run_status(run_id, "cancelled", msg="Discarded by user")

        # Trigger purge
        return PurgeService.purge_run(run_id)
