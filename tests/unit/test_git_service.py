from __future__ import annotations

import subprocess
from pathlib import Path

from tools.gimo_server.services.git_service import GitService


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_test_repo(cwd: Path, *extra_args: str) -> None:
    """Init a git repo with signing disabled (sandbox/CI safe)."""
    _git(cwd, "init", *extra_args)
    _git(cwd, "config", "commit.gpgSign", "false")


def _git_result(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def test_get_changed_files_includes_untracked_files(tmp_path: Path):
    _init_test_repo(tmp_path)
    _git(tmp_path, "config", "user.name", "Tester")
    _git(tmp_path, "config", "user.email", "tester@example.com")
    (tmp_path / "tracked.txt").write_text("base", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "init")

    (tmp_path / "new_file.py").write_text("print('x')", encoding="utf-8")
    changed = GitService.get_changed_files(tmp_path)

    assert "new_file.py" in changed


def test_get_changed_files_preserves_first_modified_filename(tmp_path: Path):
    _init_test_repo(tmp_path)
    _git(tmp_path, "config", "user.name", "Tester")
    _git(tmp_path, "config", "user.email", "tester@example.com")
    (tmp_path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "init")

    (tmp_path / "tracked.txt").write_text("changed\n", encoding="utf-8")

    changed = GitService.get_changed_files(tmp_path)

    assert changed == ["tracked.txt"]


def test_perform_merge_aborts_on_conflict_and_leaves_repo_clean(tmp_path: Path):
    _init_test_repo(tmp_path, "-b", "main")
    _git(tmp_path, "config", "user.name", "Tester")
    _git(tmp_path, "config", "user.email", "tester@example.com")
    (tmp_path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "init")

    _git(tmp_path, "checkout", "-b", "feature_a")
    (tmp_path / "tracked.txt").write_text("feature a\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "feature a")

    _git(tmp_path, "checkout", "main")
    _git(tmp_path, "checkout", "-b", "feature_b")
    (tmp_path / "tracked.txt").write_text("feature b\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "feature b")

    _git(tmp_path, "checkout", "main")
    _git(tmp_path, "checkout", "-b", "integration")

    ok, _ = GitService.perform_merge(tmp_path, "feature_a", "integration")
    assert ok is True

    ok, _ = GitService.perform_merge(tmp_path, "feature_b", "integration")
    assert ok is False

    status = _git_result(tmp_path, "status", "--short")
    assert status.returncode == 0
    assert status.stdout.strip() == ""

    checkout = _git_result(tmp_path, "checkout", "main")
    assert checkout.returncode == 0
