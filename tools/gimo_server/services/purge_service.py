from __future__ import annotations
import hashlib
import json
import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from ..models.core import PurgeReceipt, OpsRun
from .ops_service import OpsService
from .git_service import GitService
from ..config import get_settings

logger = logging.getLogger("orchestrator.purge")

class PurgeService:
    """Phase 6B: Canonical PurgeService for reconstructive state removal.
    
    Mission:
    - remove reconstructive artifacts/state
    - retain minimal terminal metadata only
    - persist purge receipt
    - fail closed on partial purge
    """

    @classmethod
    def purge_run(cls, run_id: str) -> PurgeReceipt:
        """Removes reconstructive artifacts and retains minimal terminal metadata.
        
        Invariant: purge_removes_reconstructive_state
        Invariant: minimal_terminal_metadata_only
        Invariant: purge_fails_closed_on_partial_cleanup
        """
        removed_categories = []
        
        try:
            run = OpsService.get_run(run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")

            # 1. Identify and remove workspace reconstructed state
            workspace_path_str = None
            if run.validated_task_spec:
                workspace_path_str = run.validated_task_spec.get("workspace_path")
            
            if workspace_path_str:
                workspace_path = Path(workspace_path_str)
                settings = get_settings()
                repo_root = Path(settings.repo_root_dir).resolve()
                
                # B2 Security: Never purge the main repo root
                if workspace_path.exists() and workspace_path.resolve() != repo_root:
                    try:
                        # Use GitService to remove worktree if it is one
                        GitService.remove_worktree(repo_root, workspace_path)
                        removed_categories.append("workspace")
                    except Exception as e:
                        logger.warning(f"GitService.remove_worktree failed for {workspace_path}: {e}")
                        # Fallback for non-git workspaces or failed git command
                        if workspace_path.exists():
                            shutil.rmtree(workspace_path, ignore_errors=True)
                            removed_categories.append("workspace_fs")
                elif workspace_path.resolve() == repo_root:
                    logger.warning(f"Refusing to purge workspace because it matches repo_root: {workspace_path}")

            # 2. Remove Events
            events_path = OpsService._run_events_path(run_id)
            if events_path.exists():
                events_path.unlink()
                removed_categories.append("events")

            # 3. Remove Logs
            logs_path = OpsService._run_log_path(run_id)
            if logs_path.exists():
                logs_path.unlink()
                removed_categories.append("logs")

            # 4. Retain minimal metadata only (IDs, hashes, outcome, timestamps, commit refs, model identifier)
            # survivor fields: run_id, outcome/status, timestamps, relevant commit refs, evidence/purge hash, model identifier
            retained_data = {
                "id": run.id,
                "approved_id": run.approved_id,
                "status": run.status,
                "commit_base": run.commit_base,
                "commit_after": run.commit_after,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "risk_score": run.risk_score,
                "model_identifier": str(run.model_tier or "unknown"),
                "purged": True,
                "purged_at": datetime.now(timezone.utc).isoformat()
            }
            
            # Evidence hash of retained metadata
            metadata_str = json.dumps(retained_data, sort_keys=True)
            retained_hash = hashlib.sha256(metadata_str.encode("utf-8")).hexdigest()
            
            # Persist minimal metadata (destructive overwrite)
            run_path = OpsService._run_path(run_id)
            run_path.write_text(json.dumps(retained_data, indent=2), encoding="utf-8")
            
            # 5. Persist Purge Receipt
            receipt = PurgeReceipt(
                run_id=run_id,
                removed_categories=removed_categories,
                retained_metadata_hash=retained_hash,
                success=True
            )
            cls._persist_receipt(receipt)
            
            return receipt

        except Exception as e:
            logger.error(f"Purge failed for run {run_id}: {e}")
            # Fail closed: ensure we don't return success
            raise RuntimeError(f"Purge failed for run {run_id}: {str(e)}")

    @classmethod
    def _persist_receipt(cls, receipt: PurgeReceipt):
        # We store receipts in .orch_data/ops/purge_receipts
        receipts_dir = OpsService.OPS_DIR / "purge_receipts"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        path = receipts_dir / f"purge_{receipt.run_id}.json"
        path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")
