from __future__ import annotations

import logging
import shutil
import hashlib
from dataclasses import dataclass
from pathlib import Path

from ..config import WORKTREES_DIR
from .git_service import GitService

logger = logging.getLogger("orchestrator.services.sandbox_service")


@dataclass(frozen=True)
class SandboxHandle:
    run_id: str
    repo_path: str
    worktree_path: Path
    branch_name: str
    base_ref: str


class SandboxService:
    """Service to manage isolated git worktrees for agent execution."""

    BASE_WORKTREE_PATH = WORKTREES_DIR

    @classmethod
    def _worktree_path(cls, run_id: str) -> Path:
        digest = hashlib.sha256(run_id.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return cls.BASE_WORKTREE_PATH / digest

    @classmethod
    def _branch_name(cls, run_id: str) -> str:
        digest = hashlib.sha256(run_id.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"gimo_{digest}"

    @classmethod
    def create_worktree_handle(cls, run_id: str, repo_path: str, base_ref: str = "main") -> SandboxHandle:
        cls.BASE_WORKTREE_PATH.mkdir(parents=True, exist_ok=True)
        repo_root = Path(repo_path)
        worktree_path = cls._worktree_path(run_id)
        branch_name = cls._branch_name(run_id)

        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

        GitService.create_worktree(repo_root, worktree_path, branch_name=branch_name, base_ref=base_ref)
        logger.info("Sandbox created for %s at %s", run_id, worktree_path)
        return SandboxHandle(
            run_id=run_id,
            repo_path=str(repo_root),
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_ref=base_ref,
        )

    @classmethod
    def cleanup_worktree(cls, handle: SandboxHandle) -> bool:
        try:
            GitService.remove_worktree(Path(handle.repo_path), handle.worktree_path)
            GitService.delete_branch(Path(handle.repo_path), handle.branch_name)
            logger.info("Sandbox %s cleaned up successfully.", handle.run_id)
            return True
        except Exception as exc:
            logger.error("Failed to cleanup worktree %s: %s", handle.run_id, exc)
            return False

    @classmethod
    def create_sandbox(cls, run_id: str, repo_path: str, base_ref: str = "main") -> str:
        return str(cls.create_worktree_handle(run_id, repo_path, base_ref=base_ref).worktree_path)

    @classmethod
    def cleanup_sandbox(cls, run_id: str, repo_path: str) -> bool:
        handle = SandboxHandle(
            run_id=run_id,
            repo_path=repo_path,
            worktree_path=cls._worktree_path(run_id),
            branch_name=cls._branch_name(run_id),
            base_ref="main",
        )
        return cls.cleanup_worktree(handle)
