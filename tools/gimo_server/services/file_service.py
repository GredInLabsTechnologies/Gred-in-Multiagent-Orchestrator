import hashlib
from pathlib import Path
from typing import List, Tuple

from tools.gimo_server.config import AUDIT_LOG_PATH, MAX_BYTES, MAX_LINES
from tools.gimo_server.security import audit_log, redact_sensitive_data
from tools.gimo_server.services.snapshot_service import SnapshotService


class FileService:
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
        start_line: int,
        end_line: int,
        token: str,
        truncated_marker: str = "\n# ... [TRUNCATED] ...\n",
    ) -> Tuple[str, str]:
        """
        Handles reading a file through snapshots, slicing lines, and audit logging.
        Returns (content, hash).
        """
        snapshot_path = SnapshotService.create_snapshot(target_path)

        with open(snapshot_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        # Adjust end_line if necessary
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

        audit_log(
            str(target_path),
            f"{start_line}-{end_line}",
            content_hash,
            operation="READ_SNAPSHOT",
            actor=token,
        )

        return content, content_hash
