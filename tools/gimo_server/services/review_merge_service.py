from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .git_service import GitService
from .review_purge_contract import (
    get_run_with_context,
    resolve_base_commit,
    resolve_review_source_repo_path,
    resolve_workspace_path,
)

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
        run, draft_context = get_run_with_context(run_id)
        workspace_path = resolve_workspace_path(
            run_id,
            run,
            draft_context,
            required=True,
            require_exists=True,
        )
        head_commit = GitService.get_head_commit(workspace_path)
        base_commit = resolve_base_commit(run_id, run, draft_context)

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

        review_source_repo = resolve_review_source_repo_path(
            run_id,
            run,
            draft_context,
            required=True,
            require_exists=True,
        )
        source_repo_head = GitService.get_head_commit(review_source_repo)
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
        run, draft_context = get_run_with_context(run_id)
        base_commit = resolve_base_commit(run_id, run, draft_context)

        review_source_repo = resolve_review_source_repo_path(
            run_id,
            run,
            draft_context,
            required=True,
            require_exists=True,
        )
        source_head = GitService.get_head_commit(review_source_repo)
        
        drift_detected = (source_head != base_commit)
        
        return MergePreview(
            run_id=run_id,
            source_repo_head=source_head,
            expected_base=base_commit,
            drift_detected=drift_detected,
            manual_merge_required=True, # Phase 6A strict requirement
            can_merge=not drift_detected,
            reason="Source repo has drifted from expected base" if drift_detected else "Ready for manual review/merge"
        )
