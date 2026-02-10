import hashlib
from pathlib import Path
from unittest.mock import patch

from tools.gimo_server.services.file_service import FileService


def test_tail_audit_lines_missing(tmp_path):
    with patch(
        "tools.gimo_server.services.file_service.AUDIT_LOG_PATH", tmp_path / "nonexistent.log"
    ):
        assert FileService.tail_audit_lines() == []


def test_tail_audit_lines_success(tmp_path):
    log_file = tmp_path / "audit.log"
    log_file.write_text("line1\nline2\nline3", encoding="utf-8")
    with patch("tools.gimo_server.services.file_service.AUDIT_LOG_PATH", log_file):
        lines = FileService.tail_audit_lines(limit=2)
        assert len(lines) == 2
        assert lines == ["line2", "line3"]


def test_tail_audit_lines_error(tmp_path):
    log_file = tmp_path / "audit.log"
    log_file.mkdir()  # Make it a directory to cause read error
    with patch("tools.gimo_server.services.file_service.AUDIT_LOG_PATH", log_file):
        assert FileService.tail_audit_lines() == []


@patch("tools.gimo_server.services.file_service.SnapshotService.create_snapshot")
@patch("tools.gimo_server.services.file_service.audit_log")
def test_get_file_content(mock_audit, mock_snapshot, tmp_path):
    mock_file = tmp_path / "test.py"
    mock_file.write_text("line1\nline2\nline3\nline4", encoding="utf-8")

    mock_snapshot.return_value = mock_file

    content, content_hash = FileService.get_file_content(
        Path("dummy.py"), start_line=1, end_line=10, token="test-token"
    )

    assert "line1" in content
    assert "line4" in content
    assert content_hash == hashlib.sha256(content.encode()).hexdigest()
    mock_audit.assert_called_once()


@patch("tools.gimo_server.services.file_service.SnapshotService.create_snapshot")
@patch("tools.gimo_server.services.file_service.audit_log")
@patch("tools.gimo_server.services.file_service.MAX_LINES", 2)
def test_get_file_content_truncated_lines(mock_audit, mock_snapshot, tmp_path):
    mock_file = tmp_path / "test.py"
    mock_file.write_text("line1\nline2\nline3\nline4", encoding="utf-8")
    mock_snapshot.return_value = mock_file

    content, _ = FileService.get_file_content(
        Path("dummy.py"), start_line=1, end_line=10, token="test-token"
    )
    # MAX_LINES is 2, so it should only show line1 and line2 + truncated marker
    assert "line1" in content
    assert "line2" in content
    assert "line3" not in content
    assert "TRUNCATED" in content


@patch("tools.gimo_server.services.file_service.SnapshotService.create_snapshot")
@patch("tools.gimo_server.services.file_service.audit_log")
@patch("tools.gimo_server.services.file_service.MAX_BYTES", 10)
def test_get_file_content_truncated_bytes(mock_audit, mock_snapshot, tmp_path):
    mock_file = tmp_path / "test.py"
    mock_file.write_text("very long content that exceeds max bytes", encoding="utf-8")
    mock_snapshot.return_value = mock_file

    content, _ = FileService.get_file_content(
        Path("dummy.py"), start_line=1, end_line=1, token="test-token"
    )
    assert len(content.encode("utf-8")) <= 10 + len("\n# ... [TRUNCATED] ...\n")
    assert "TRUNCATED" in content
