import shutil
import uuid
from pathlib import Path
from typing import Optional

from tools.gimo_server.services.git_service import GitService

class EphemeralRepoService:
    def __init__(self, ephemeral_repos_dir: Path, repo_mirrors_dir: Path, purge_quarantine_dir: Path):
        self.ephemeral_repos_dir = ephemeral_repos_dir
        self.repo_mirrors_dir = repo_mirrors_dir
        self.purge_quarantine_dir = purge_quarantine_dir
        
        # Ensure directories exist
        self.ephemeral_repos_dir.mkdir(parents=True, exist_ok=True)
        self.repo_mirrors_dir.mkdir(parents=True, exist_ok=True)
        self.purge_quarantine_dir.mkdir(parents=True, exist_ok=True)

    def get_or_update_mirror(self, repo_url: str, mirror_id: str) -> Path:
        """Provide or update a bare clone mirror."""
        mirror_dir = self.repo_mirrors_dir / mirror_id
        if not mirror_dir.exists():
            GitService.init_mirror(self.repo_mirrors_dir, repo_url, mirror_dir)
        else:
            GitService.fetch_mirror(mirror_dir)
        return mirror_dir

    def create_ephemeral_workspace(self, source_repo: Path, base_commit: str, branch_name: Optional[str] = None) -> Path:
        """Create a decoupled local clone and checkout from a generic local source."""
        workspace_id = str(uuid.uuid4())
        target_dir = self.ephemeral_repos_dir / workspace_id
        
        # We need a base dir for the command when cloning, we can use the source_repo's parent
        GitService.clone_local(source_repo.parent, source_repo, target_dir)
        GitService.checkout_commit(target_dir, base_commit)
        
        if branch_name:
            GitService.create_ephemeral_branch(target_dir, branch_name, base_commit)
            
        return target_dir

    def create_ephemeral_workspace_from_mirror(self, mirror_dir: Path, base_commit: str, branch_name: Optional[str] = None) -> Path:
        """Create a decoupled local clone and checkout explicitly from a managed mirror."""
        if not mirror_dir.is_relative_to(self.repo_mirrors_dir):
            raise ValueError(f"Mirror must be located in {self.repo_mirrors_dir}")
        return self.create_ephemeral_workspace(mirror_dir, base_commit, branch_name)

    def destroy_workspace(self, workspace_dir: Path) -> None:
        """Destroy/purge workspace."""
        if not workspace_dir.is_relative_to(self.ephemeral_repos_dir):
            raise ValueError(f"Can only destroy ephemeral workspaces in {self.ephemeral_repos_dir}")
        if workspace_dir.exists():
            import os, stat
            def remove_readonly(func, path, _):
                try:
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                except Exception:
                    pass
            shutil.rmtree(workspace_dir, onerror=remove_readonly)

