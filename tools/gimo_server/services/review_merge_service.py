from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .ops_service import OpsService
from .git_service import GitService
from ..config import get_settings

logger = logging.getLogger("orchestrator.review_merge")


class ReviewBundle(BaseModel):
    """Canonical Phase 6A review artifact."""
    run_id: str
    base_commit: str
    head_commit: str
    changed_files: List[str]
    diff_summary: str
    logs: List[Dict[str, Any]]
    test_evidence: Optional[str] = None
    lint_evidence: Optional[str] = None
    drift_detected: bool = False
    source_repo_head: Optional[str] = None


class MergePreview(BaseModel):
    """Minimal merge preview metadata."""
    run_id: str
    source_repo_head: str
    expected_base: str
    drift_detected: bool
    manual_merge_required: bool = True
    can_merge: bool = False
    reason: Optional[str] = None


class ReviewMergeService:
    """Phase 6A: Review bundle generation and merge preview logic.
    
    Ensures source repo remains untouched and drift is detected.
    """

    @classmethod
    def build_review_bundle(cls, run_id: str) -> ReviewBundle:
        """Builds a bundle of all evidence required for review.
        
        Invariant: review_bundle_contains_changed_files
        Invariant: review_bundle_contains_diff_or_diff_summary
        Invariant: review_bundle_carries_available_logs_and_test_evidence
        """
        run = OpsService.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        # Get workspace from run context/metadata
        # Phase 5B added validated_task_spec which may contain workspace_path
        workspace_path_str = None
        if run.validated_task_spec:
            workspace_path_str = run.validated_task_spec.get("workspace_path")
        
        if not workspace_path_str:
            approved = OpsService.get_approved(run.approved_id)
            if approved:
                draft = OpsService.get_draft(approved.draft_id)
                if draft and draft.context:
                    workspace_path_str = draft.context.get("workspace_path")

        if not workspace_path_str:
            raise ValueError(f"No workspace_path found for run {run_id}")
        
        workspace_path = Path(workspace_path_str)
        if not workspace_path.exists():
            raise ValueError(f"Workspace path {workspace_path} does not exist")

        head_commit = GitService.get_head_commit(workspace_path)
        base_commit = run.commit_base or (run.validated_task_spec.get("base_commit") if run.validated_task_spec else None)
        
        if not base_commit:
            raise RuntimeError(f"Base commit for run {run_id} cannot be proven. Failing closed.")

        # Gather evidence from the ephemeral workspace (untouched source repo)
        changed_files = GitService.get_changed_files(workspace_path, base=base_commit)
        # Use diff_text for more detail than --stat
        diff_summary = GitService.get_diff_text(workspace_path, base=base_commit)
        logs = run.log or []
        
        # Extract evidence from logs if available
        test_evidence = None
        lint_evidence = None
        for entry in reversed(logs):
            msg = str(entry.get("msg", ""))
            if "tests_output_tail=" in msg:
                 test_evidence = msg.split("tests_output_tail=", 1)[1]
            if "lint_output_tail=" in msg:
                 lint_evidence = msg.split("lint_output_tail=", 1)[1]

        # Drift detection
        settings = get_settings()
        repo_root = Path(settings.repo_root_dir)
        source_repo_head = GitService.get_head_commit(repo_root)
        drift_detected = (source_repo_head != base_commit)

        return ReviewBundle(
            run_id=run_id,
            base_commit=base_commit,
            head_commit=head_commit,
            changed_files=changed_files,
            diff_summary=diff_summary,
            logs=logs,
            test_evidence=test_evidence,
            lint_evidence=lint_evidence,
            drift_detected=drift_detected,
            source_repo_head=source_repo_head
        )

    @classmethod
    def get_merge_preview(cls, run_id: str) -> MergePreview:
        """Detects base drift and enforces manual-merge requirements.
        
        Invariant: merge_preview_detects_base_drift
        Invariant: manual_merge_only
        """
        run = OpsService.get_run(run_id)
        if not run:
             raise ValueError(f"Run {run_id} not found")
        
        base_commit = run.commit_base or (run.validated_task_spec.get("base_commit") if run.validated_task_spec else None)
        if not base_commit:
             raise RuntimeError(f"Base commit for run {run_id} cannot be proven. Failing closed.")

        settings = get_settings()
        repo_root = Path(settings.repo_root_dir)
        source_head = GitService.get_head_commit(repo_root)
        
        drift_detected = (source_head != base_commit)
        
        return MergePreview(
            run_id=run_id,
            source_repo_head=source_head,
            expected_base=base_commit,
            drift_detected=drift_detected,
            manual_merge_required=True, # Phase 6A strict requirement
            can_merge=not drift_detected,
            reason="Source repo has drifted from base" if drift_detected else "Ready for manual review/merge"
        )
