import re
import subprocess
import importlib.util
from pathlib import Path
from typing import Optional

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
    """Gestiona repositorios locales, worktrees y operaciones Git."""
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

    @staticmethod
    def add_worktree(base_dir: Path, worktree_path: Path, branch: str = None) -> None:
        """Adds a new git worktree at the specified path."""
        try:
            cmd = ["git", "worktree", "add", str(worktree_path)]
            if branch:
                cmd.append(_sanitize_git_ref(branch))
            else:
                # If no branch, we might want --detach or just current HEAD
                # For isolation, we usually want to work on a specific branch or a detached HEAD
                cmd.append("--detach")

            process = subprocess.Popen(
                cmd,
                cwd=base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            _, stderr = process.communicate(timeout=SUBPROCESS_TIMEOUT)
            if process.returncode != 0:
                raise RuntimeError(f"Git worktree add error: {stderr.strip()}")
        except Exception as e:
            raise RuntimeError(f"Internal git worktree add error: {str(e)}")

    @staticmethod
    def remove_worktree(base_dir: Path, worktree_path: Path) -> None:
        """Removes a git worktree and cleans up the directory."""
        try:
            # Running from base_dir ensures git knows the context
            process = subprocess.Popen(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            _, stderr = process.communicate(timeout=SUBPROCESS_TIMEOUT)
            if process.returncode != 0:
                # If it's already gone, we don't necessarily want to fail
                if "is not a working tree" in stderr:
                    return
                raise RuntimeError(f"Git worktree remove error: {stderr.strip()}")
            
            # Additional cleanup for Windows or stubborn directories
            import shutil
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
        except Exception as e:
            raise RuntimeError(f"Internal git worktree remove error: {str(e)}")

    @staticmethod
    def list_worktrees(base_dir: Path) -> list[str]:
        """Lists active git worktrees."""
        try:
            process = subprocess.Popen(
                ["git", "worktree", "list", "--porcelain"],
                cwd=base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate(timeout=SUBPROCESS_TIMEOUT)
            if process.returncode != 0:
                raise RuntimeError(f"Git worktree list error: {stderr.strip()}")
            
            worktrees = []
            for line in stdout.splitlines():
                if line.startswith("worktree "):
                    worktrees.append(line.split("worktree ", 1)[1])
            return worktrees
        except Exception as e:
            raise RuntimeError(f"Internal git worktree list error: {str(e)}")

    @staticmethod
    def _run_git(base_dir: Path, args: list[str], *, timeout: Optional[int] = None) -> tuple[int, str, str]:
        process = subprocess.Popen(
            ["git", *args],
            cwd=base_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate(timeout=timeout or SUBPROCESS_TIMEOUT)
        return process.returncode, stdout.strip(), stderr.strip()

    @staticmethod
    def get_head_commit(base_dir: Path) -> str:
        code, out, err = GitService._run_git(base_dir, ["rev-parse", "HEAD"])
        if code != 0:
            raise RuntimeError(f"Git rev-parse error: {err}")
        return out

    @staticmethod
    def is_worktree_clean(base_dir: Path) -> bool:
        code, out, err = GitService._run_git(base_dir, ["status", "--porcelain"])
        if code != 0:
            raise RuntimeError(f"Git status error: {err}")
        return out == ""

    @staticmethod
    def run_tests(base_dir: Path) -> tuple[bool, str]:
        process = subprocess.Popen(
            ["python", "-m", "pytest", "-q"],
            cwd=base_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate(timeout=max(SUBPROCESS_TIMEOUT, 120))
        out = (stdout or "") + ("\n" + stderr if stderr else "")
        return process.returncode == 0, out.strip()

    @staticmethod
    def run_lint_typecheck(base_dir: Path) -> tuple[bool, str]:
        outputs: list[str] = []

        # Lint gate: prefer ruff when installed.
        if importlib.util.find_spec("ruff") is not None:
            p_lint = subprocess.Popen(
                ["python", "-m", "ruff", "check", "."],
                cwd=base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            lint_out, lint_err = p_lint.communicate(timeout=max(SUBPROCESS_TIMEOUT, 120))
            outputs.append((lint_out or "") + ("\n" + lint_err if lint_err else ""))
            if p_lint.returncode != 0:
                return False, "\n".join(outputs).strip()
        else:
            outputs.append("ruff not installed; lint gate skipped")

        # Typecheck gate: prefer mypy when installed.
        if importlib.util.find_spec("mypy") is not None:
            p_type = subprocess.Popen(
                ["python", "-m", "mypy", "tools/gimo_server"],
                cwd=base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            type_out, type_err = p_type.communicate(timeout=max(SUBPROCESS_TIMEOUT, 120))
            outputs.append((type_out or "") + ("\n" + type_err if type_err else ""))
            if p_type.returncode != 0:
                return False, "\n".join(outputs).strip()
        else:
            outputs.append("mypy not installed; typecheck gate skipped")

        # Fallback deterministic syntax check when no tool is installed.
        if all("not installed" in o for o in outputs):
            p_syntax = subprocess.Popen(
                ["python", "-m", "compileall", "-q", "tools/gimo_server"],
                cwd=base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            syn_out, syn_err = p_syntax.communicate(timeout=max(SUBPROCESS_TIMEOUT, 120))
            outputs.append((syn_out or "") + ("\n" + syn_err if syn_err else ""))
            if p_syntax.returncode != 0:
                return False, "\n".join(outputs).strip()

        return True, "\n".join(outputs).strip()

    @staticmethod
    def dry_run_merge(base_dir: Path, source_ref: str, target_ref: str) -> tuple[bool, str]:
        src = _sanitize_git_ref(source_ref)
        tgt = _sanitize_git_ref(target_ref)
        # Simulate by merge-tree first (safe), then merge --no-commit --no-ff on a detached checkout not required here.
        code, out, err = GitService._run_git(base_dir, ["merge-tree", tgt, src])
        if code != 0:
            return False, err or out
        return True, out

    @staticmethod
    def perform_merge(base_dir: Path, source_ref: str, target_ref: str) -> tuple[bool, str]:
        src = _sanitize_git_ref(source_ref)
        tgt = _sanitize_git_ref(target_ref)
        code_co, _, err_co = GitService._run_git(base_dir, ["checkout", tgt])
        if code_co != 0:
            return False, err_co
        code_m, out_m, err_m = GitService._run_git(base_dir, ["merge", "--no-ff", src])
        if code_m != 0:
            return False, err_m or out_m
        return True, out_m

    @staticmethod
    def rollback_to_commit(base_dir: Path, commit_before: str) -> tuple[bool, str]:
        commit = _sanitize_git_ref(commit_before)
        code, out, err = GitService._run_git(base_dir, ["reset", "--hard", commit])
        if code != 0:
            return False, err or out
        return True, out
