import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.gimo_server.services.file_service import FileService
from tools.gimo_server.services.git_service import GitService
from tools.gimo_server.services.snapshot_service import SnapshotService

# --- FileService Tests ---


def test_tail_audit_lines_missing(tmp_path):
    with patch("tools.gimo_server.services.file_service.AUDIT_LOG_PATH", tmp_path / "none"):
        assert FileService.tail_audit_lines() == []


def test_tail_audit_lines_success(tmp_path):
    log = tmp_path / "audit.log"
    log.write_text("l1\nl2\nl3", encoding="utf-8")
    with patch("tools.gimo_server.services.file_service.AUDIT_LOG_PATH", log):
        assert FileService.tail_audit_lines(limit=2) == ["l2", "l3"]


def test_tail_audit_lines_exception(tmp_path):
    log = tmp_path / "audit.log"
    log.mkdir()
    with patch("tools.gimo_server.services.file_service.AUDIT_LOG_PATH", log):
        assert FileService.tail_audit_lines() == []


def test_get_file_content_complex(tmp_path):
    f = tmp_path / "test.py"
    f.write_text("line1\nline2\nline3\nline4\nline5\nline6")
    with patch(
        "tools.gimo_server.services.file_service.SnapshotService.create_snapshot",
        return_value=f,
    ):
        with patch("tools.gimo_server.services.file_service.MAX_LINES", 2):
            with patch("tools.gimo_server.services.file_service.MAX_BYTES", 1000):
                content, h = FileService.get_file_content(f, 1, 5, "token")
                assert "line1\nline2" in content
                assert "[TRUNCATED]" in content


def test_get_file_content_redaction(tmp_path):
    f = tmp_path / "test.py"
    f.write_text("token = 'abcdef1234567890abcdef1234567890abcdef1234567890'")
    with patch(
        "tools.gimo_server.services.file_service.SnapshotService.create_snapshot",
        return_value=f,
    ):
        content, _ = FileService.get_file_content(f, 1, 1, "token")
        assert "[REDACTED]" in content


def test_get_file_content_byte_truncation(tmp_path):
    f = tmp_path / "test.py"
    f.write_text("some content long enough")
    with patch(
        "tools.gimo_server.services.file_service.SnapshotService.create_snapshot",
        return_value=f,
    ):
        with patch("tools.gimo_server.services.file_service.MAX_BYTES", 5):
            content, _ = FileService.get_file_content(f, 1, 1, "token")
            assert "[TRUNCATED]" in content


# --- GitService Tests ---


def test_git_get_diff_success():
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("diff output", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc
        diff = GitService.get_diff(Path("."), "main", "HEAD")
        assert diff == "diff output"


def test_git_get_diff_error():
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "git error")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc
        with pytest.raises(RuntimeError, match="Git error: git error"):
            GitService.get_diff(Path("."), "main", "HEAD")


def test_git_get_diff_exception():
    with patch("subprocess.Popen", side_effect=Exception("spawn error")):
        with pytest.raises(RuntimeError, match="Internal git execution error"):
            GitService.get_diff(Path("."), "main", "HEAD")


def test_git_list_repos_success(tmp_path):
    (tmp_path / "repo1").mkdir()
    (tmp_path / "none").mkdir()
    with patch("pathlib.Path.exists", return_value=False):
        assert GitService.list_repos(Path("/none")) == []
    repos = GitService.list_repos(tmp_path)
    assert len(repos) >= 1


# --- SnapshotService Tests ---


def test_snapshot_ensure_dir(tmp_path):
    snap_dir = tmp_path / "snaps"
    with patch("tools.gimo_server.services.snapshot_service.SNAPSHOT_DIR", snap_dir):
        SnapshotService.ensure_snapshot_dir()
        assert snap_dir.exists()
        with patch.object(Path, "chmod", side_effect=Exception("perm error")):
            SnapshotService.ensure_snapshot_dir()


def test_snapshot_create(tmp_path):
    snap_dir = tmp_path / "snaps"
    snap_dir.mkdir()
    target = tmp_path / "target.py"
    target.write_text("content")
    with patch("tools.gimo_server.services.snapshot_service.SNAPSHOT_DIR", snap_dir):
        snap_path = SnapshotService.create_snapshot(target)
        assert snap_path.exists()


def test_snapshot_secure_delete_success(tmp_path):
    f = tmp_path / "del"
    f.write_text("data")
    SnapshotService.secure_delete(f)
    assert not f.exists()


def test_snapshot_secure_delete_error(tmp_path):
    f = tmp_path / "err"
    f.write_text("ok")
    with patch("builtins.open", side_effect=Exception("io")):
        SnapshotService.secure_delete(f)
        assert not f.exists()


def test_snapshot_secure_delete_total_fail(tmp_path):
    f = tmp_path / "fail"
    f.write_text("ok")
    with patch.object(Path, "unlink", side_effect=Exception("unlink")):
        with patch("builtins.open", side_effect=Exception("io")):
            SnapshotService.secure_delete(f)
            assert f.exists()


def test_snapshot_cleanup_no_dir():
    with patch(
        "tools.gimo_server.services.snapshot_service.SNAPSHOT_DIR", Path("nonexistent")
    ):
        SnapshotService.cleanup_old_snapshots()


def test_snapshot_cleanup_success(tmp_path):
    snap_dir = tmp_path / "snaps"
    snap_dir.mkdir()

    now = time.time()
    with patch("tools.gimo_server.services.snapshot_service.SNAPSHOT_DIR", snap_dir):
        with patch("tools.gimo_server.services.snapshot_service.SNAPSHOT_TTL", 60):
            mock_item = MagicMock(spec=Path)
            mock_item.is_file.return_value = True
            mock_item.stat.return_value.st_mtime = now - 100
            mock_item.stat.return_value.st_mode = 0o100644

            with patch.object(Path, "iterdir", return_value=[mock_item]):
                with patch.object(SnapshotService, "secure_delete") as mock_delete:
                    SnapshotService.cleanup_old_snapshots()
                    mock_delete.assert_called_once_with(mock_item)
