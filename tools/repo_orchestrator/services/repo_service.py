import os
import shutil
from pathlib import Path
from typing import List, Optional

from tools.repo_orchestrator.config import (
    ALLOWED_EXTENSIONS,
    BASE_DIR,
    REPO_ROOT_DIR,
    SEARCH_EXCLUDE_DIRS,
    VITAMINIZE_PACKAGE,
)
from tools.repo_orchestrator.models import RepoEntry
from tools.repo_orchestrator.security import (
    load_repo_registry,
    redact_sensitive_data,
    save_repo_registry,
)
from tools.repo_orchestrator.services.git_service import GitService


class RepoService:
    @staticmethod
    def list_repos() -> List[RepoEntry]:
        repos_data = GitService.list_repos(REPO_ROOT_DIR)
        return [RepoEntry(name=r["name"], path=r["path"]) for r in repos_data]

    @staticmethod
    def ensure_repo_registry(repos: List[RepoEntry]) -> dict:
        registry = load_repo_registry()
        registry_paths = {Path(r).resolve() for r in registry.get("repos", [])}
        for repo in repos:
            repo_path = Path(repo.path).resolve()
            if repo_path not in registry_paths:
                registry["repos"].append(str(repo_path))

        if registry.get("active_repo"):
            active = Path(registry["active_repo"]).resolve()
            if active not in registry_paths:
                registry["active_repo"] = str(active)

        save_repo_registry(registry)
        return registry

    @staticmethod
    def vitaminize_repo(target_repo: Path) -> List[str]:
        created = []
        for rel in VITAMINIZE_PACKAGE:
            source = BASE_DIR / rel
            dest = target_repo / rel
            if source.is_dir():
                if dest.exists():
                    continue
                shutil.copytree(source, dest)
                created.append(str(dest))
            elif source.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    continue
                shutil.copy2(source, dest)
                created.append(str(dest))
        return created

    @staticmethod
    def walk_tree(target: Path, max_depth: int) -> List[str]:
        result = []
        base_parts = len(target.parts)
        for root, dirs, files in os.walk(target):
            current_path = Path(root)
            depth = len(current_path.parts) - base_parts
            if depth > max_depth:
                continue

            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d
                not in ["node_modules", ".venv", ".git", "dist", "build", *SEARCH_EXCLUDE_DIRS]
            ]

            for f in files:
                file_path = current_path / f
                if file_path.suffix in ALLOWED_EXTENSIONS:
                    result.append(str(file_path.relative_to(target)))
                    if len(result) >= 2000:
                        return result
        return result

    @staticmethod
    def perform_search(base_dir: Path, q: str, ext: Optional[str]) -> List[dict]:
        hits = []
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if not RepoService._should_skip_dir(d)]
            for f in files:
                if ext and not f.endswith(ext):
                    continue
                file_path = Path(root) / f
                if file_path.suffix not in ALLOWED_EXTENSIONS:
                    continue
                hits.extend(RepoService._search_in_file(file_path, base_dir, q))
                if len(hits) >= 50:
                    return hits[:50]
        return hits

    @staticmethod
    def _search_in_file(file_path: Path, base_dir: Path, q: str) -> List[dict]:
        file_hits = []
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f_obj:
                for i, line in enumerate(f_obj):
                    if q in line:
                        file_hits.append(
                            {
                                "file": str(file_path.relative_to(base_dir)),
                                "line": i + 1,
                                "content": redact_sensitive_data(line.strip()),
                            }
                        )
                        if len(file_hits) >= 50:
                            break
        except (OSError, UnicodeDecodeError) as exc:
            # Log and continue; individual file failures shouldn't crash search
            import logging

            logging.getLogger("orchestrator.repo").warning(
                "Failed to search %s: %s", file_path, exc
            )
        return file_hits

    @staticmethod
    def _should_skip_dir(d: str) -> bool:
        return d.startswith(".") or d in ["node_modules", ".venv", ".git", *SEARCH_EXCLUDE_DIRS]
