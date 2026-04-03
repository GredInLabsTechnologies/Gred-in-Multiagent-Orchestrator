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
    """Gestiona repositorios locales, worktrees y operaciones Git.
    
    **Git primitives only. Not the final isolation design.**
    """
    @staticmethod
    def get_diff(base_dir: Path, base: str = "main", head: str = "HEAD") -> str:
        try:
            # Sanitize git refs to prevent argument injection
            safe_base = _sanitize_git_ref(base)
            safe_head = _sanitize_git_ref(head)

            process = subprocess.Popen(
                ["git", "diff", "--stat", f"{safe_base}..{safe_head}"],
                cwd=base_dir,
                stdin=subprocess.DEVNULL,
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
            if item.is_dir() and not item.name.startswith(".") and (item / ".git").exists():
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
                cmd.append("--detach")

            process = subprocess.Popen(
                cmd,
                cwd=base_dir,
                stdin=subprocess.DEVNULL,
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
    def create_worktree(base_dir: Path, worktree_path: Path, branch_name: str, base_ref: str = "HEAD") -> None:
        """Create a new worktree on a fresh branch starting from base_ref."""
        try:
            safe_branch = _sanitize_git_ref(branch_name)
            safe_base = _sanitize_git_ref(base_ref)
            process = subprocess.Popen(
                ["git", "worktree", "add", "-b", safe_branch, str(worktree_path), safe_base],
                cwd=base_dir,
                stdin=subprocess.DEVNULL,
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
                stdin=subprocess.DEVNULL,
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
                stdin=subprocess.DEVNULL,
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
            stdin=subprocess.DEVNULL,
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
    def get_current_branch(base_dir: Path) -> str:
        code, out, err = GitService._run_git(base_dir, ["rev-parse", "--abbrev-ref", "HEAD"])
        if code != 0:
            raise RuntimeError(f"Git branch detection error: {err}")
        return out

    @staticmethod
    def is_worktree_clean(base_dir: Path) -> bool:
        code, out, err = GitService._run_git(base_dir, ["status", "--porcelain"])
        if code != 0:
            raise RuntimeError(f"Git status error: {err}")
        return out == ""

    @staticmethod
    def commit_all(base_dir: Path, message: str) -> str:
        code_add, _, err_add = GitService._run_git(base_dir, ["add", "-A"])
        if code_add != 0:
            raise RuntimeError(f"Git add error: {err_add}")
        code_commit, out_commit, err_commit = GitService._run_git(
            base_dir,
            [
                "-c",
                "user.name=GIMO",
                "-c",
                "user.email=gimo@example.invalid",
                "commit",
                "-m",
                message,
            ],
        )
        if code_commit != 0:
            raise RuntimeError(f"Git commit error: {err_commit or out_commit}")
        return GitService.get_head_commit(base_dir)

    @staticmethod
    def get_diff_text(base_dir: Path, base: str = "HEAD") -> str:
        safe_base = _sanitize_git_ref(base)
        code, out, err = GitService._run_git(base_dir, ["diff", safe_base])
        if code != 0:
            raise RuntimeError(f"Git diff error: {err or out}")
        code_status, out_status, err_status = GitService._run_git(base_dir, ["status", "--short"])
        if code_status != 0:
            raise RuntimeError(f"Git status error: {err_status or out_status}")
        status_section = f"\n[status]\n{out_status}" if out_status else ""
        return f"{out}{status_section}".strip()

    @staticmethod
    def get_changed_files(base_dir: Path, base: str = "HEAD") -> list[str]:
        code, out, err = GitService._run_git(base_dir, ["status", "--porcelain"])
        if code != 0:
            raise RuntimeError(f"Git status --porcelain error: {err or out}")

        changed: list[str] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            # _run_git() strips global stdout, so the first porcelain line may lose its
            # leading space (" M file.py" -> "M file.py"). Parse both canonical forms.
            if len(line) >= 3 and line[2] == " ":
                payload = line[3:].strip()
            elif len(line) >= 2 and line[1] == " ":
                payload = line[2:].strip()
            else:
                payload = line.strip()
            if " -> " in payload:
                payload = payload.split(" -> ", 1)[1].strip()
            if payload:
                changed.append(payload)
        return sorted(set(changed))

    @staticmethod
    def create_branch(base_dir: Path, branch_name: str, start_point: str) -> None:
        safe_branch = _sanitize_git_ref(branch_name)
        safe_start = _sanitize_git_ref(start_point)
        code, out, err = GitService._run_git(base_dir, ["checkout", "-B", safe_branch, safe_start])
        if code != 0:
            raise RuntimeError(f"Git create branch error: {err or out}")

    @staticmethod
    def fast_forward_branch(base_dir: Path, target_ref: str, source_ref: str) -> tuple[bool, str]:
        target = _sanitize_git_ref(target_ref)
        source = _sanitize_git_ref(source_ref)
        code_co, _, err_co = GitService._run_git(base_dir, ["checkout", target])
        if code_co != 0:
            return False, err_co
        code_merge, out_merge, err_merge = GitService._run_git(base_dir, ["merge", "--ff-only", source])
        if code_merge != 0:
            return False, err_merge or out_merge
        return True, out_merge

    @staticmethod
    def delete_branch(base_dir: Path, branch_name: str) -> None:
        safe_branch = _sanitize_git_ref(branch_name)
        code, out, err = GitService._run_git(base_dir, ["branch", "-D", safe_branch])
        if code != 0:
            raise RuntimeError(f"Git delete branch error: {err or out}")

    @staticmethod
    def run_tests(base_dir: Path) -> tuple[bool, str]:
        process = subprocess.Popen(
            ["python", "-m", "pytest", "-q"],
            cwd=base_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate(timeout=max(SUBPROCESS_TIMEOUT, 120))
        out = (stdout or "") + ("\n" + stderr if stderr else "")
        return process.returncode == 0, out.strip()

    @staticmethod
    def _run_ruff(base_dir: Path, outputs: list[str]) -> bool:
        if importlib.util.find_spec("ruff") is not None:
            p_lint = subprocess.Popen(
                ["python", "-m", "ruff", "check", "."],
                cwd=base_dir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            lint_out, lint_err = p_lint.communicate(timeout=max(SUBPROCESS_TIMEOUT, 120))
            outputs.append((lint_out or "") + ("\n" + lint_err if lint_err else ""))
            return p_lint.returncode == 0
        outputs.append("ruff not installed; lint gate skipped")
        return True

    @staticmethod
    def _run_mypy(base_dir: Path, outputs: list[str]) -> bool:
        if importlib.util.find_spec("mypy") is not None:
            p_type = subprocess.Popen(
                ["python", "-m", "mypy", "tools/gimo_server"],
                cwd=base_dir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            type_out, type_err = p_type.communicate(timeout=max(SUBPROCESS_TIMEOUT, 120))
            outputs.append((type_out or "") + ("\n" + type_err if type_err else ""))
            return p_type.returncode == 0
        outputs.append("mypy not installed; typecheck gate skipped")
        return True

    @staticmethod
    def _run_compileall(base_dir: Path, outputs: list[str]) -> bool:
        if all("not installed" in o for o in outputs):
            p_syntax = subprocess.Popen(
                ["python", "-m", "compileall", "-q", "tools/gimo_server"],
                cwd=base_dir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            syn_out, syn_err = p_syntax.communicate(timeout=max(SUBPROCESS_TIMEOUT, 120))
            outputs.append((syn_out or "") + ("\n" + syn_err if syn_err else ""))
            return p_syntax.returncode == 0
        return True

    @staticmethod
    def run_lint_typecheck(base_dir: Path) -> tuple[bool, str]:
        outputs: list[str] = []

        if not GitService._run_ruff(base_dir, outputs):
            return False, "\n".join(outputs).strip()

        if not GitService._run_mypy(base_dir, outputs):
            return False, "\n".join(outputs).strip()

        if not GitService._run_compileall(base_dir, outputs):
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
            abort_code, abort_out, abort_err = GitService._run_git(base_dir, ["merge", "--abort"])
            if abort_code != 0 and "MERGE_HEAD missing" not in (abort_err or abort_out):
                return False, f"{err_m or out_m}\n[merge-abort failed] {abort_err or abort_out}".strip()
            return False, err_m or out_m
        return True, out_m

    @staticmethod
    def rollback_to_commit(base_dir: Path, commit_before: str) -> tuple[bool, str]:
        commit = _sanitize_git_ref(commit_before)
        code, out, err = GitService._run_git(base_dir, ["reset", "--hard", commit])
        if code != 0:
            return False, err or out
        return True, out

    @staticmethod
    def current_head(base_dir: Path) -> str:
        return GitService.get_head_commit(base_dir)

    @staticmethod
    def clean_repo_check(base_dir: Path) -> bool:
        return GitService.is_worktree_clean(base_dir)

    @staticmethod
    def clone_local(base_dir: Path, source_repo: Path, target_dir: Path) -> None:
        src = str(source_repo.resolve())
        tgt = str(target_dir.resolve())
        code, out, err = GitService._run_git(base_dir, ["clone", "--local", src, tgt])
        if code != 0:
            raise RuntimeError(f"Git clone local error: {err or out}")

    @staticmethod
    def init_mirror(base_dir: Path, source_url: str, target_dir: Path) -> None:
        tgt = str(target_dir.resolve())
        code, out, err = GitService._run_git(base_dir, ["clone", "--mirror", source_url, tgt])
        if code != 0:
            raise RuntimeError(f"Git init mirror error: {err or out}")

    @staticmethod
    def fetch_mirror(mirror_dir: Path) -> None:
        code, out, err = GitService._run_git(mirror_dir, ["fetch", "--prune"])
        if code != 0:
            raise RuntimeError(f"Git fetch mirror error: {err or out}")

    @staticmethod
    def fetch_local_ref(base_dir: Path, source_repo: Path, ref: str) -> None:
        src = str(source_repo.resolve())
        safe_ref = _sanitize_git_ref(ref)
        code, out, err = GitService._run_git(base_dir, ["fetch", src, safe_ref])
        if code != 0:
            raise RuntimeError(f"Git fetch local ref error: {err or out}")

    @staticmethod
    def checkout_commit(base_dir: Path, commit_hash: str) -> None:
        commit = _sanitize_git_ref(commit_hash)
        code, out, err = GitService._run_git(base_dir, ["checkout", commit])
        if code != 0:
            raise RuntimeError(f"Git checkout commit error: {err or out}")

    @staticmethod
    def create_ephemeral_branch(base_dir: Path, branch_name: str, base_commit: str) -> None:
        branch = _sanitize_git_ref(branch_name)
        commit = _sanitize_git_ref(base_commit)
        code, out, err = GitService._run_git(base_dir, ["checkout", "-B", branch, commit])
        if code != 0:
            raise RuntimeError(f"Git create ephemeral branch error: {err or out}")

    @staticmethod
    def bundle_diff(base_dir: Path, output_file: Path, base_commit: str, head_commit: str) -> None:
        base = _sanitize_git_ref(base_commit)
        head = _sanitize_git_ref(head_commit)
        out_path = str(output_file.resolve())
        code, out, err = GitService._run_git(base_dir, ["bundle", "create", out_path, f"{base}..{head}"])
        if code != 0:
            raise RuntimeError(f"Git bundle error: {err or out}")

    @staticmethod
    def apply_bundle(base_dir: Path, bundle_file: Path) -> None:
        bundle_path = str(bundle_file.resolve())
        code, out, err = GitService._run_git(base_dir, ["pull", bundle_path])
        if code != 0:
            raise RuntimeError(f"Git apply bundle error: {err or out}")

