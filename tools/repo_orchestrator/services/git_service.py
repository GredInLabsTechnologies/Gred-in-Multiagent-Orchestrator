import subprocess
from pathlib import Path

from tools.repo_orchestrator.config import SUBPROCESS_TIMEOUT


class GitService:
    @staticmethod
    def get_diff(base_dir: Path, base: str = "main", head: str = "HEAD") -> str:
        try:
            process = subprocess.Popen(
                ["git", "diff", "--stat", base, head],
                cwd=base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate(timeout=SUBPROCESS_TIMEOUT)
            if process.returncode != 0:
                raise RuntimeError(f"Git error: {stderr.strip()}")
            return stdout
        except Exception as e:
            raise RuntimeError(f"Internal git execution error: {str(e)}")

    @staticmethod
    def list_repos(root_dir: Path) -> list[dict]:
        if not root_dir.exists():
            return []
        entries = []
        for item in root_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                entries.append({"name": item.name, "path": str(item.resolve())})
        return sorted(entries, key=lambda x: x["name"].lower())
