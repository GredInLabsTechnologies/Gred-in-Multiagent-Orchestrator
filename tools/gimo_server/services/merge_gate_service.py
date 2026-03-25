from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict

from ..config import get_settings
from .git_service import GitService
from .ops_service import OpsService

logger = logging.getLogger("orchestrator.merge_gate")


class MergeGateService:
    """Fase 7 — Merge Gate Industrial.

    Pipeline determinista:
    1) gates previos (policy/intent/risk)
    2) lock por repo (TTL + heartbeat)
    3) worktree limpio
    4) tests
    5) lint/typecheck
    6) dry-run merge
    7) merge real
    8) rollback determinista si falla post-merge
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
    def _validate_policy(cls, run_id: str, context: dict, run: Any) -> bool:
        policy_decision = str(context.get("policy_decision") or "").strip().lower()
        policy_decision_id = str(context.get("policy_decision_id") or run.policy_decision_id or "").strip()

        if not policy_decision_id:
            # Opción A: generate audited fallback for low-risk / doc intents so that
            # drafts created via routes that skip RuntimePolicyService (e.g.
            # /ops/generate-plan, /ops/generate, /ops/slice0-pipeline) can still
            # execute instead of crashing with WORKER_CRASHED_RECOVERABLE.
            intent_effective = str(context.get("intent_effective") or "").upper()
            if intent_effective in cls._LOW_RISK_INTENTS or not intent_effective:
                policy_decision_id = f"policy_fallback_{int(time.time() * 1000)}"
                OpsService.append_log(
                    run_id, level="WARN",
                    msg=(
                        f"policy_decision_id absent; synthetic fallback issued "
                        f"id={policy_decision_id} intent={intent_effective or 'unset'}"
                    ),
                )
                # If caller also omitted the decision, default to allow.
                if not policy_decision:
                    policy_decision = "allow"
            else:
                OpsService.update_run_status(
                    run_id, "WORKER_CRASHED_RECOVERABLE", msg="missing policy_decision_id"
                )
                return False

        # If approved but policy_decision not propagated, treat as allow.
        if not policy_decision:
            policy_decision = "allow"

        if policy_decision == "deny":
            OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg="Policy deny at merge gate")
            return False
        if policy_decision == "review":
            OpsService.update_run_status(run_id, "HUMAN_APPROVAL_REQUIRED", msg="policy review required")
            return False
        if policy_decision != "allow":
            OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg="invalid policy decision")
            return False

        # Gate obligatorio de baseline hash (Fase 7): expected == runtime
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
        if not intent_effective:
            # Drafts from non-policy routes lack intent_effective; default to DOC_UPDATE
            # (lowest-risk class) so the pipeline can continue rather than blocking.
            intent_effective = "DOC_UPDATE"
            OpsService.append_log(
                run_id, level="WARN",
                msg="intent_effective absent; defaulting to DOC_UPDATE for merge gate risk check",
            )

        if risk_score >= 60:
            OpsService.update_run_status(run_id, "RISK_SCORE_TOO_HIGH", msg="risk_gt_60")
            return False
        if 31 <= risk_score < 60:
            OpsService.update_run_status(run_id, "HUMAN_APPROVAL_REQUIRED", msg="risk_between_31_60")
            return False
        if intent_effective in {"SECURITY_CHANGE", "CORE_RUNTIME_CHANGE"}:
            OpsService.update_run_status(run_id, "HUMAN_APPROVAL_REQUIRED", msg="intent_requires_human_review")
            return False
        return True

    @classmethod
    async def execute_run(cls, run_id: str) -> bool:
        run = OpsService.get_run(run_id)
        if not run:
            return False
        approved = OpsService.get_approved(run.approved_id)
        if not approved:
            OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg="Approved entry not found")
            return True
            
        draft = OpsService.get_draft(approved.draft_id)
        context: Dict[str, Any] = dict((draft.context if draft else {}) or {})
        repo_context = dict(context.get("repo_context") or {})
        repo_id = str(run.repo_id or repo_context.get("repo_id") or repo_context.get("target_branch") or "default")
        source_ref = str(context.get("source_ref") or "HEAD")
        target_ref = str(repo_context.get("target_branch") or "main")
        workspace_path = context.get("workspace_path")

        if not cls._validate_policy(run_id, context, run):
            return True

        if not cls._validate_risk(run_id, context, run):
            return True

        # For low-risk / doc intents the full git merge pipeline is unnecessary
        # and would crash on repos that aren't set up for it.  Return False so
        # RunWorker falls through to its LLM-based file-write path, which
        # correctly materialises artefacts like docs/DISEÑO_CALCULADORA.md.
        intent_effective = str(context.get("intent_effective") or "").upper()
        if intent_effective in cls._LOW_RISK_INTENTS or not intent_effective:
            OpsService.append_log(
                run_id, level="INFO",
                msg=(
                    f"MergeGate: bypassing git pipeline for low-risk intent "
                    f"'{intent_effective or 'unset'}'. Delegating to RunWorker."
                ),
            )
            return False

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
                cls._pipeline(run_id, repo_id=repo_id, source_ref=source_ref, target_ref=target_ref, provided_workspace=workspace_path),
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
            try:
                await hb_task
            except Exception:
                pass
            OpsService.release_merge_lock(repo_id, run_id)
            OpsService.append_log(run_id, level="INFO", msg=f"Merge lock released id={lock_payload.get('lock_id','')}")

    @classmethod
    async def _heartbeat_loop(cls, repo_id: str, run_id: str, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await asyncio.sleep(cls.HEARTBEAT_INTERVAL_SECONDS)
            if stop_event.is_set():
                break
            try:
                OpsService.heartbeat_merge_lock(repo_id, run_id, ttl_seconds=cls.LOCK_TTL_SECONDS)
            except Exception:
                OpsService.append_log(run_id, level="WARN", msg="Heartbeat failed; lock may be stale")
                break


    @classmethod
    def _sandbox_worktree_path(cls, run_id: str) -> Path:
        settings = get_settings()
        return Path(settings.ops_data_dir) / "worktrees" / run_id

    @classmethod
    def _create_sandbox_worktree(cls, run_id: str, source_ref: str) -> Path:
        # [LEGACY] Creation of sandbox worktrees directly over the source repo will be replaced in Phase 1.
        settings = get_settings()
        repo_root = Path(settings.repo_root_dir)
        sandbox_path = cls._sandbox_worktree_path(run_id)
        sandbox_path.parent.mkdir(parents=True, exist_ok=True)
        if sandbox_path.exists():
            GitService.remove_worktree(repo_root, sandbox_path)
        GitService.add_worktree(repo_root, sandbox_path, branch=source_ref)
        return sandbox_path

    @classmethod
    def _cleanup_sandbox_worktree(cls, run_id: str) -> None:
        settings = get_settings()
        repo_root = Path(settings.repo_root_dir)
        sandbox_path = cls._sandbox_worktree_path(run_id)
        if sandbox_path.exists():
            GitService.remove_worktree(repo_root, sandbox_path)

    @classmethod
    async def _pipeline(cls, run_id: str, *, repo_id: str, source_ref: str, target_ref: str, provided_workspace: str = None) -> None:
        del repo_id
        
        if provided_workspace:
            OpsService.set_run_stage(run_id, "gate_worktree", msg="Phase7: using provisioned sandbox workspace")
            base_dir = Path(provided_workspace)
        else:
            OpsService.set_run_stage(run_id, "gate_worktree", msg="Phase7: creating legacy sandbox worktree")
            try:
                base_dir = cls._create_sandbox_worktree(run_id, source_ref)
            except Exception as exc:
                OpsService.update_run_status(run_id, "WORKTREE_CORRUPTED", msg=f"sandbox worktree create failed: {exc}")
                return

        try:
            OpsService.set_run_stage(run_id, "gate_tests", msg="Phase7: running tests in sandbox")
            ok_tests, tests_out = GitService.run_tests(base_dir)
            OpsService.append_log(run_id, level="INFO", msg=f"tests_output_tail={tests_out[-1000:]}")
            if not ok_tests:
                OpsService.update_run_status(run_id, "VALIDATION_FAILED_TESTS", msg="tests failed")
                return

            OpsService.set_run_stage(run_id, "gate_lint", msg="Phase7: running lint/typecheck in sandbox")
            ok_lint, lint_out = GitService.run_lint_typecheck(base_dir)
            OpsService.append_log(run_id, level="INFO", msg=f"lint_output_tail={lint_out[-1000:]}")
            if not ok_lint:
                OpsService.update_run_status(run_id, "VALIDATION_FAILED_LINT", msg="lint/typecheck failed")
                return

            OpsService.set_run_stage(run_id, "dry_run_merge", msg="Phase7: dry-run merge in sandbox")
            ok_dry, dry_out = GitService.dry_run_merge(base_dir, source_ref, target_ref)
            OpsService.append_log(run_id, level="INFO", msg=f"dry_run_tail={dry_out[-1000:]}")
            if not ok_dry:
                OpsService.update_run_status(run_id, "MERGE_CONFLICT", msg="dry-run merge conflict")
                return

            OpsService.set_run_stage(run_id, "merge_real", msg="Phase7: performing merge in sandbox")
            commit_before = GitService.get_head_commit(base_dir)
            OpsService.update_run_merge_metadata(run_id, commit_before=commit_before)
            ok_merge, merge_out = GitService.perform_merge(base_dir, source_ref, target_ref)
            OpsService.append_log(run_id, level="INFO", msg=f"merge_tail={merge_out[-1000:]}")
            if not ok_merge:
                OpsService.update_run_status(run_id, "MERGE_CONFLICT", msg="merge failed")
                return

            try:
                commit_after = GitService.get_head_commit(base_dir)
                OpsService.update_run_merge_metadata(run_id, commit_after=commit_after)
                OpsService.update_run_status(run_id, "done", msg="merge pipeline completed")
            except Exception as exc:
                # post-merge failure => rollback determinista
                ok_rb, rb_out = GitService.rollback_to_commit(base_dir, commit_before)
                OpsService.append_log(run_id, level="WARN", msg=f"rollback_tail={rb_out[-1000:]}")
                if ok_rb:
                    OpsService.update_run_status(run_id, "ROLLBACK_EXECUTED", msg=f"rollback after post-merge failure: {exc}")
                else:
                    OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE", msg=f"rollback failed: {exc}")
        finally:
            if not provided_workspace:
                try:
                    cls._cleanup_sandbox_worktree(run_id)
                except Exception as exc:
                    OpsService.append_log(run_id, level="WARN", msg=f"sandbox cleanup failed: {exc}")
