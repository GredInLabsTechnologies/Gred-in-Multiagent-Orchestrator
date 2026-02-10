import re
import subprocess
from pathlib import Path

from tools.gimo_server.config import SUBPROCESS_TIMEOUT

# Pattern for valid git ref names (branch, tag, commit hash)
_VALID_GIT_REF = re.compile(r"^[a-zA-Z0-9_.\-/]+$")


def _sanitize_git_ref(ref: str) -> str:
    """Validate and sanitize git ref to prevent argument injection."""
    ref = ref.strip()
    if not ref:
        raise ValueError("Git ref cannot be empty")
    if len(ref) > 256:
        raise ValueError("Git ref too long")
    if ref.startswith("-"):
        raise ValueError("Git ref cannot start with dash")
    if not _VALID_GIT_REF.match(ref):
        raise ValueError(f"Invalid git ref: {ref}")
    return ref


class GitService:
    @staticmethod
    def get_diff(base_dir: Path, base: str = "main", head: str = "HEAD") -> str:
        try:
            # Sanitize git refs to prevent argument injection
            safe_base = _sanitize_git_ref(base)
            safe_head = _sanitize_git_ref(head)

            process = subprocess.Popen(
                ["git", "diff", "--stat", "--", safe_base, safe_head],
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
