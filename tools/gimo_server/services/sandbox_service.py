import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("orchestrator.services.sandbox_service")

class SandboxService:
    """Service to manage isolated git worktrees for agent execution."""
    
    # Required by Phase 2 / Phase A: Baseline isolation
    BASE_WORKTREE_PATH = Path("C:/gimo_work/worktrees") if os.name == 'nt' else Path("/tmp/gimo_work/worktrees")

    @classmethod
    def create_sandbox(cls, run_id: str, repo_path: str, base_ref: str = "main") -> str:
        """Create a git worktree for the given run ID."""
        cls.BASE_WORKTREE_PATH.mkdir(parents=True, exist_ok=True)
        worktree_path = cls.BASE_WORKTREE_PATH / run_id

        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

        branch_name = f"gimo_{run_id}"
        cmd = ["git", "worktree", "add", str(worktree_path), "-b", branch_name, base_ref]
        
        try:
            subprocess.run(cmd, cwd=repo_path, check=True, capture_output=True, text=True)
            logger.info(f"Sandbox created for {run_id} at {worktree_path}")
            return str(worktree_path)
        except subprocess.CalledProcessError as e:
            # If the branch already exists, we could just checkout, but standard is fail-fast
            logger.error(f"Failed to create worktree: {e.stderr}")
            raise RuntimeError(f"Sandbox creation failed: {e.stderr}")

    @classmethod
    def cleanup_sandbox(cls, run_id: str, repo_path: str) -> bool:
        """Remove the worktree and its branch dynamically."""
        worktree_path = cls.BASE_WORKTREE_PATH / run_id
        if not worktree_path.exists():
            return False
            
        branch_name = f"gimo_{run_id}"
        try:
            # Force remove worktree
            subprocess.run(["git", "worktree", "remove", "-f", str(worktree_path)], 
                           cwd=repo_path, check=True, capture_output=True)
            
            # Force delete temporary branch
            subprocess.run(["git", "branch", "-D", branch_name], 
                           cwd=repo_path, check=False, capture_output=True)
            
            logger.info(f"Sandbox {run_id} cleaned up successfully.")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to cleanup worktree {run_id}: {e.stderr}")
            return False
