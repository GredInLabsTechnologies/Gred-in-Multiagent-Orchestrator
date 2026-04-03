from __future__ import annotations
import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from ..config import (
    BASE_DIR, REPO_ROOT_DIR, ALLOWED_EXTENSIONS, 
    SEARCH_EXCLUDE_DIRS, AUDIT_LOG_PATH, MAX_BYTES, MAX_LINES, SUBPROCESS_TIMEOUT
)
from ..security import audit_log, redact_sensitive_data
from .snapshot_service import SnapshotService
from ..ops_models import RepoEntry

# Git Ref Regex from git_service
import re
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

def _is_path_safe(path: Path) -> bool:
    """Check if the path is within allowed directories."""
    try:
        abs_path = path.resolve()
        return any(str(abs_path).startswith(str(d.resolve())) for d in [BASE_DIR, REPO_ROOT_DIR])
    except Exception:
        return False

class WorkspaceService:
    """Consolidated service for file, git, and repository operations."""

    # --- File Operations (from FileService) ---

    @staticmethod
    def tail_audit_lines(limit: int = 200) -> List[str]:
        if not AUDIT_LOG_PATH.exists():
            return []
        try:
            lines = AUDIT_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
            return lines[-limit:]
        except Exception:
            return []

    @staticmethod
    def get_file_content(
        target_path: Path,
        start_line: int = 1,
        end_line: int = MAX_LINES,
        token: str = "",
        truncated_marker: str = "\n# ... [TRUNCATED] ...\n",
    ) -> Tuple[str, str]:
        if not _is_path_safe(target_path):
            raise ValueError(f"Access denied to path: {target_path}")
        snapshot_path = SnapshotService.create_snapshot(target_path)
        with open(snapshot_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        if end_line - start_line + 1 > MAX_LINES:
            end_line = start_line + MAX_LINES - 1
            final_truncated_marker = truncated_marker
        else:
            final_truncated_marker = ""

        content = "".join(lines[max(0, start_line - 1) : end_line])
        content = redact_sensitive_data(content)

        if len(content.encode("utf-8")) > MAX_BYTES:
            content = content[:MAX_BYTES] + truncated_marker
        elif final_truncated_marker and len(lines) > end_line:
            content += final_truncated_marker

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        audit_log(str(target_path), f"{start_line}-{end_line}", content_hash, operation="READ_SNAPSHOT", actor=token)
        return content, content_hash

    @staticmethod
    def write_file(target_path: Path, content: str, token: str) -> str:
        if not _is_path_safe(target_path):
            raise ValueError(f"Access denied to path: {target_path}")
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            audit_log(str(target_path), "0", content_hash, operation="WRITE_FILE", actor=token)
            return f"Successfully wrote to {target_path}"
        except Exception as e:
            raise IOError(f"Failed to write to {target_path}: {e}")

    # --- Git Operations (from GitService) ---

    @staticmethod
    def _run_git(base_dir: Path, args: list[str], *, timeout: Optional[int] = None) -> tuple[int, str, str]:
        process = subprocess.Popen(["git", *args], cwd=base_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=timeout or SUBPROCESS_TIMEOUT)
        return process.returncode, stdout.strip(), stderr.strip()

    @staticmethod
    def get_diff(base_dir: Path, base: str = "main", head: str = "HEAD") -> str:
        safe_base = _sanitize_git_ref(base)
        safe_head = _sanitize_git_ref(head)
        code, out, err = WorkspaceService._run_git(base_dir, ["diff", "--stat", f"{safe_base}..{safe_head}"])
        if code != 0:
            raise RuntimeError(f"Git diff error: {err}")
        return out

    @staticmethod
    def add_worktree(base_dir: Path, worktree_path: Path, branch: str = None) -> None:
        cmd = ["worktree", "add", str(worktree_path)]
        if branch:
            cmd.append(_sanitize_git_ref(branch))
        else:
            cmd.append("--detach")
        code, _, err = WorkspaceService._run_git(base_dir, cmd)
        if code != 0:
            raise RuntimeError(f"Git worktree add error: {err}")

    @staticmethod
    def remove_worktree(base_dir: Path, worktree_path: Path) -> None:
        code, _, err = WorkspaceService._run_git(base_dir, ["worktree", "remove", "--force", str(worktree_path)])
        if code != 0 and "is not a working tree" not in err:
            raise RuntimeError(f"Git worktree remove error: {err}")
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

    @staticmethod
    def perform_merge(base_dir: Path, source_ref: str, target_ref: str) -> tuple[bool, str]:
        src = _sanitize_git_ref(source_ref)
        tgt = _sanitize_git_ref(target_ref)
        code_co, _, err_co = WorkspaceService._run_git(base_dir, ["checkout", tgt])
        if code_co != 0:
            return False, err_co
        code_m, out_m, err_m = WorkspaceService._run_git(base_dir, ["merge", "--no-ff", src])
        return code_m == 0, err_m or out_m

    # --- Repository Operations (from RepoService) ---

    @staticmethod
    def list_repos() -> List[RepoEntry]:
        if not REPO_ROOT_DIR.exists():
            return []
        repos = []
        for item in REPO_ROOT_DIR.iterdir():
            if item.is_dir() and not item.name.startswith(".") and (item / ".git").exists():
                repos.append(RepoEntry(name=item.name, path=str(item.resolve())))
        return sorted(repos, key=lambda x: x.name.lower())

    @staticmethod
    def walk_tree(target: Path, max_depth: int) -> List[str]:
        result = []
        base_parts = len(target.parts)
        for root, dirs, files in os.walk(target):
            current_path = Path(root)
            depth = len(current_path.parts) - base_parts
            if depth > max_depth:
                continue
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ["node_modules", ".venv", ".git", "dist", "build", *SEARCH_EXCLUDE_DIRS]]
            for f in files:
                file_path = current_path / f
                if file_path.suffix in ALLOWED_EXTENSIONS:
                    result.append(str(file_path.relative_to(target)))
                    if len(result) >= 2000:
                        return result
        return result
