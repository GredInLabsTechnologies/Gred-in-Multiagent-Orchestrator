from __future__ import annotations

import logging
import hashlib
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from .ephemeral_repo_service import EphemeralRepoService

logger = logging.getLogger("orchestrator.services.sandbox_service")


@dataclass(frozen=True)
class SandboxHandle:
    run_id: str
    repo_path: str
    worktree_path: Path
    branch_name: str
    base_ref: str


class SandboxService:
    """Provision isolated execution sandboxes without mutating the source repo."""
    BASE_WORKTREE_PATH: Path = get_settings().ephemeral_repos_dir

    @classmethod
    def _workspace_id(cls, run_id: str) -> str:
        digest = hashlib.sha256(run_id.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return digest

    @classmethod
    def _workspace_path(cls, run_id: str) -> Path:
        settings = get_settings()
        return settings.ephemeral_repos_dir / cls._workspace_id(run_id)

    @classmethod
    def _branch_name(cls, run_id: str) -> str:
        digest = hashlib.sha256(run_id.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"gimo_{digest}"

    @classmethod
    def _ephemeral_repo_service(cls) -> EphemeralRepoService:
        settings = get_settings()
        return EphemeralRepoService(
            settings.ephemeral_repos_dir,
            settings.repo_mirrors_dir,
            settings.purge_quarantine_dir,
        )

    @classmethod
    def create_worktree_handle(cls, run_id: str, repo_path: str, base_ref: str = "main") -> SandboxHandle:
        repo_root = Path(repo_path).resolve()
        branch_name = cls._branch_name(run_id)
        service = cls._ephemeral_repo_service()
        workspace_path = service.create_ephemeral_workspace(
            repo_root,
            base_ref,
            branch_name=branch_name,
            workspace_id=cls._workspace_id(run_id),
        )
        logger.info("Sandbox created for %s at %s [ephemeral clone]", run_id, workspace_path)
        return SandboxHandle(
            run_id=run_id,
            repo_path=str(repo_root),
            worktree_path=workspace_path,
            branch_name=branch_name,
            base_ref=base_ref,
        )

    @classmethod
    def cleanup_worktree(cls, handle: SandboxHandle) -> bool:
        try:
            settings = get_settings()
            workspace_path = handle.worktree_path.resolve()
            ephemeral_root = settings.ephemeral_repos_dir.resolve()

            if not workspace_path.is_relative_to(ephemeral_root):
                logger.warning(
                    "Refusing to cleanup non-canonical sandbox path for %s: %s",
                    handle.run_id,
                    workspace_path,
                )
                return False

            cls._ephemeral_repo_service().destroy_workspace(workspace_path)
            logger.info("Sandbox %s cleaned up successfully [ephemeral clone].", handle.run_id)
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
            worktree_path=cls._workspace_path(run_id),
            branch_name=cls._branch_name(run_id),
            base_ref="main",
        )
        return cls.cleanup_worktree(handle)
