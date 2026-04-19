from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict

from .git_service import GitService
from .ops import OpsService
from .review_purge_contract import resolve_authoritative_repo_path, resolve_workspace_path

logger = logging.getLogger("orchestrator.merge_gate")


class MergeGateService:
    """Fase 7 — Merge Gate Industrial.

    Pipeline determinista con contrato de merge manual separado (Fase 7B):
    1) gates previos (policy/intent/risk)
    2) lock por repo (TTL + heartbeat)
    3) sandbox limpio (provisioned)
    4) tests
    5) lint/typecheck
    6) dry-run merge
    7) PAUSE: transition to AWAITING_MERGE
    8) perform_manual_merge: explicit human trigger for repo mutation
    """

    LOCK_TTL_SECONDS = 120
    HEARTBEAT_INTERVAL_SECONDS = 30
    PIPELINE_TIMEOUT_SECONDS = 900

    # Intent classes considered low-risk for policy fallback purposes.
    _LOW_RISK_INTENTS = frozenset({
        "DOC_UPDATE", "DOC_WRITE", "DOC_CREATE", "DOCUMENTATION",
        "DOCS", "FILE_WRITE", "FILE_CREATE",
    })

    @classmethod
    def _prepare_workspace_source_ref(cls, run_id: str, workspace_path: Path) -> str:
        if GitService.clean_repo_check(workspace_path):
            return GitService.get_head_commit(workspace_path)
        return GitService.commit_all(workspace_path, f"GIMO workspace snapshot for run {run_id}")

    @classmethod
    def _validate_policy(cls, run_id: str, context: dict, run: Any) -> bool:
        policy_decision = str(context.get("policy_decision") or "").strip().lower()
        policy_decision_id = str(context.get("policy_decision_id") or run.policy_decision_id or "").strip()
        human_approval_granted = bool(context.get("human_approval_granted"))

        if not policy_decision_id:
            intent_effective = str(context.get("intent_effective") or "").upper()
            if intent_effective in cls._LOW_RISK_INTENTS or not intent_effective:
                policy_decision_id = f"policy_fallback_{int(time.time() * 1000)}"
                OpsService.append_log(
                    run_id, level="WARN",
                    msg=f"policy_decision_id absent; synthetic fallback issued id={policy_decision_id}"
                )
                if not policy_decision:
                    policy_decision = "allow"
            else:
                OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg="missing policy_decision_id")
                return False

        if not policy_decision:
            policy_decision = "allow"

        if policy_decision == "deny":
            OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg="Policy deny at merge gate")
            return False
        if policy_decision == "review":
            if human_approval_granted:
                OpsService.append_log(run_id, level="INFO", msg="MergeGate: persisted handover approval accepted policy review")
                return True
            OpsService.update_run_status(run_id, "HUMAN_APPROVAL_REQUIRED", msg="policy review required")
            return False
        if policy_decision != "allow":
            OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg="invalid policy decision")
            return False

        policy_hash_expected = str(context.get("policy_hash_expected") or "")
        policy_hash_runtime = str(context.get("policy_hash_runtime") or "")
        if policy_hash_expected and policy_hash_runtime and policy_hash_expected != policy_hash_runtime:
            OpsService.update_run_status(run_id, "BASELINE_TAMPER_DETECTED", msg="policy hash mismatch at merge gate")
            return False
        return True

    @classmethod
    def _validate_risk(cls, run_id: str, context: dict, run: Any) -> bool:
        risk_score = float(context.get("risk_score") or run.risk_score or 0.0)
        intent_effective = str(context.get("intent_effective") or "")
        human_approval_granted = bool(context.get("human_approval_granted"))
        
        if risk_score >= 60:
            OpsService.update_run_status(run_id, "RISK_SCORE_TOO_HIGH", msg="risk_gt_60")
            return False
        if 31 <= risk_score < 60:
            if human_approval_granted:
                OpsService.append_log(run_id, level="INFO", msg="MergeGate: persisted handover approval accepted medium-risk review")
                return True
            OpsService.update_run_status(run_id, "HUMAN_APPROVAL_REQUIRED", msg="risk_between_31_60")
            return False
        if intent_effective in {"SECURITY_CHANGE", "CORE_RUNTIME_CHANGE"}:
            if human_approval_granted:
                OpsService.append_log(run_id, level="INFO", msg="MergeGate: persisted handover approval accepted intent review")
                return True
            OpsService.update_run_status(run_id, "HUMAN_APPROVAL_REQUIRED", msg="intent_requires_human_review")
            return False
        return True

    @classmethod
    async def execute_run(cls, run_id: str) -> bool:
        run = OpsService.get_run(run_id)
        if not run: return False

        if str(getattr(run, "status", None) or "pending") == "pending":
            updated_run = OpsService.update_run_status(run_id, "running", msg="merge gate execution started")
            if updated_run is not None:
                run = updated_run
        
        approved = OpsService.get_approved(run.approved_id)
        if not approved:
            OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg="Approved entry not found")
            return True
            
        draft = OpsService.get_draft(approved.draft_id)
        context: Dict[str, Any] = dict((draft.context if draft else {}) or {})
        if getattr(run, "resume_context", None):
            context.update(dict(run.resume_context or {}))
        repo_context = dict(context.get("repo_context") or {})
        repo_id = str(run.repo_id or repo_context.get("repo_id") or "default")
        source_ref = str(context.get("source_ref") or "HEAD")
        target_ref = str(repo_context.get("target_branch") or "main")

        if not cls._validate_policy(run_id, context, run): return True
        if not cls._validate_risk(run_id, context, run): return True

        intent_effective = str(context.get("intent_effective") or "").upper()
        if intent_effective in cls._LOW_RISK_INTENTS or not intent_effective:
            OpsService.append_log(run_id, level="INFO", msg=f"MergeGate: bypassing git pipeline for low-risk intent '{intent_effective or 'unset'}'.")
            return False

        try:
            workspace_path = str(resolve_workspace_path(run_id, run, context, required=True, require_exists=True))
            authoritative_repo_path = str(
                resolve_authoritative_repo_path(
                    run_id,
                    run,
                    context,
                    required=True,
                    require_exists=True,
                )
            )
        except Exception as exc:
            OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg=str(exc))
            return True

        if not workspace_path:
            msg = "Missing canonical workspace_path; sandbox worktree fallback is disabled."
            OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg=msg)
            return True

        OpsService.recover_stale_lock(repo_id)
        try:
            lock_payload = OpsService.acquire_merge_lock(repo_id, run_id, ttl_seconds=cls.LOCK_TTL_SECONDS)
        except RuntimeError:
            OpsService.update_run_status(run_id, "MERGE_LOCKED", msg="merge lock already active")
            return True

        stop_heartbeat = asyncio.Event()
        hb_task = asyncio.create_task(cls._heartbeat_loop(repo_id, run_id, stop_heartbeat))

        try:
            await asyncio.wait_for(
                cls._pipeline(
                    run_id,
                    repo_id=repo_id,
                    source_ref=source_ref,
                    target_ref=target_ref,
                    provided_workspace=workspace_path,
                    authoritative_repo=authoritative_repo_path,
                ),
                timeout=cls.PIPELINE_TIMEOUT_SECONDS,
            )
            return True
        except asyncio.TimeoutError:
            OpsService.update_run_status(run_id, "PIPELINE_TIMEOUT", msg="merge pipeline timeout")
            return True
        except Exception as exc:
            logger.exception("merge gate crashed for run %s", run_id)
            OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg=f"{exc}")
            return True
        finally:
            stop_heartbeat.set()
            try: await hb_task
            except Exception: pass
            OpsService.release_merge_lock(repo_id, run_id)
            OpsService.append_log(run_id, level="INFO", msg=f"Merge lock released id={lock_payload.get('lock_id','')}")

    @classmethod
    async def _heartbeat_loop(cls, repo_id: str, run_id: str, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await asyncio.sleep(cls.HEARTBEAT_INTERVAL_SECONDS)
            if stop_event.is_set(): break
            try:
                OpsService.heartbeat_merge_lock(repo_id, run_id, ttl_seconds=cls.LOCK_TTL_SECONDS)
            except Exception: break

    @classmethod
    async def _pipeline(
        cls,
        run_id: str,
        *,
        repo_id: str,
        source_ref: str,
        target_ref: str,
        provided_workspace: str,
        authoritative_repo: str,
    ) -> None:
        del repo_id
        workspace_dir = Path(provided_workspace).resolve()
        authoritative_dir = Path(authoritative_repo).resolve()
        effective_source_ref = source_ref

        try:
            # 1. Tests in Sandbox
            OpsService.set_run_stage(run_id, "gate_tests", msg="Phase7: running tests in sandbox")
            ok_tests, tests_out = GitService.run_tests(workspace_dir)
            if not ok_tests:
                OpsService.update_run_status(run_id, "VALIDATION_FAILED_TESTS", msg="tests failed")
                return

            # 2. Lint/Typecheck in Sandbox
            OpsService.set_run_stage(run_id, "gate_lint", msg="Phase7: running lint/typecheck in sandbox")
            ok_lint, lint_out = GitService.run_lint_typecheck(workspace_dir)
            if not ok_lint:
                OpsService.update_run_status(run_id, "VALIDATION_FAILED_LINT", msg="lint/typecheck failed")
                return

            # 3. Dry-run merge on the authoritative repo using the workspace as the source of truth.
            OpsService.set_run_stage(run_id, "dry_run_merge", msg="Phase7: dry-run merge against authoritative repo")
            if workspace_dir != authoritative_dir:
                effective_source_ref = cls._prepare_workspace_source_ref(run_id, workspace_dir)
                GitService.fetch_local_ref(authoritative_dir, workspace_dir, effective_source_ref)
                dry_run_source_ref = "FETCH_HEAD"
            else:
                dry_run_source_ref = source_ref
            ok_dry, dry_out = GitService.dry_run_merge(authoritative_dir, dry_run_source_ref, target_ref)
            if not ok_dry:
                OpsService.update_run_status(run_id, "MERGE_CONFLICT", msg="dry-run merge conflict")
                return

            # Phase 7B Mandatory Pause: transition to AWAITING_MERGE.
            # NO merge_real here. 
            commit_before = GitService.get_head_commit(authoritative_dir)
            OpsService.update_run_merge_metadata(run_id, commit_before=commit_before)
            OpsService.update_run_status(run_id, "AWAITING_MERGE", msg="Gate passed; awaiting manual merge command.")
            
        finally: pass

    @classmethod
    async def perform_manual_merge(cls, run_id: str) -> bool:
        """Executes the final merge_real step for a run in AWAITING_MERGE status."""
        run = OpsService.get_run(run_id)
        if not run or run.status != "AWAITING_MERGE":
            raise ValueError(f"Run {run_id} is not in AWAITING_MERGE status")

        approved = OpsService.get_approved(run.approved_id)
        draft = OpsService.get_draft(approved.draft_id)
        context = dict((draft.context if draft else {}) or {})
        repo_context = dict(context.get("repo_context") or {})
        source_ref = str(context.get("source_ref") or "HEAD")
        target_ref = str(repo_context.get("target_branch") or "main")
        workspace_path = str(resolve_workspace_path(run_id, run, context, required=True, require_exists=True))
        authoritative_repo_path = str(
            resolve_authoritative_repo_path(
                run_id,
                run,
                context,
                required=True,
                require_exists=True,
            )
        )

        workspace_dir = Path(workspace_path).resolve()
        authoritative_dir = Path(authoritative_repo_path).resolve()
        commit_before = run.commit_before or GitService.get_head_commit(authoritative_dir)

        OpsService.set_run_stage(run_id, "merge_real", msg="Phase7: performing authoritative manual merge")
        if workspace_dir != authoritative_dir:
            source_ref = cls._prepare_workspace_source_ref(run_id, workspace_dir)
            GitService.fetch_local_ref(authoritative_dir, workspace_dir, source_ref)
            merge_source_ref = "FETCH_HEAD"
        else:
            merge_source_ref = source_ref
        ok_merge, merge_out = GitService.perform_merge(authoritative_dir, merge_source_ref, target_ref)
        
        if not ok_merge:
            OpsService.update_run_status(run_id, "MERGE_CONFLICT", msg="manual merge failed")
            return False

        try:
            commit_after = GitService.get_head_commit(authoritative_dir)
            OpsService.update_run_merge_metadata(run_id, commit_after=commit_after)
            OpsService.update_run_status(run_id, "done", msg="manual merge completed successfully")
            return True
        except Exception as exc:
            # Post-merge failure (e.g. metadata update) triggers rollback
            ok_rb, rb_out = GitService.rollback_to_commit(authoritative_dir, commit_before)
            if ok_rb:
                OpsService.update_run_status(run_id, "ROLLBACK_EXECUTED", msg=f"rollback after manual merge error: {exc}")
            else:
                OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg=f"rollback failed: {exc}")
            return False
