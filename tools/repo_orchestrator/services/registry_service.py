import json
from pathlib import Path
from tools.repo_orchestrator.config import REPO_REGISTRY_PATH

class RegistryService:
    @staticmethod
    def load_registry() -> dict:
        if not REPO_REGISTRY_PATH.exists():
            return {"active_repo": None, "repos": []}
        try:
            return json.loads(REPO_REGISTRY_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"active_repo": None, "repos": []}

    @staticmethod
    def save_registry(data: dict):
        REPO_REGISTRY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def get_active_repo_dir() -> Path:
        registry = RegistryService.load_registry()
        active = registry.get("active_repo")
        if active:
            path = Path(active).resolve()
            if path.exists():
                return path
        # Fallback to current dir if nothing active
        return Path.cwd()

    @staticmethod
    def set_active_repo(path: Path) -> dict:
        registry = RegistryService.load_registry()
        registry["active_repo"] = str(path.resolve())
        RegistryService.save_registry(registry)
        return registry

    @staticmethod
    def ensure_repo_in_registry(repos: list) -> dict:
        """
        Ensures that the given list of repos are in the registry.
        'repos' is a list of RepoEntry objects or dicts with a 'path' attribute.
        """
        registry = RegistryService.load_registry()
        # Convert existing paths to resolved Path objects for comparison
        registry_paths = {Path(r).resolve() for r in registry.get("repos", [])}
        
        modified = False
        for repo in repos:
            # Handle both object and dict access
            path_str = getattr(repo, 'path', repo.get('path') if isinstance(repo, dict) else str(repo))
            repo_path = Path(path_str).resolve()
            
            if repo_path not in registry_paths:
                registry["repos"].append(str(repo_path))
                registry_paths.add(repo_path)
                modified = True
        
        if registry.get("active_repo"):
            active = Path(registry["active_repo"]).resolve()
            if active not in registry_paths:
                # If active repo is not in the list (e.g. manually set), add it? 
                # Or just ensure the path string is normalized.
                registry["active_repo"] = str(active)
                modified = True
        
        if modified:
            RegistryService.save_registry(registry)
            
        return registry
