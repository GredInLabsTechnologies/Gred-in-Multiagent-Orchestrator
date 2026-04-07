import hashlib
from pathlib import Path
from typing import List, Tuple

from tools.gimo_server.config import AUDIT_LOG_PATH, MAX_BYTES, MAX_LINES
from tools.gimo_server.security import audit_log, redact_sensitive_data
from tools.gimo_server.services.snapshot_service import SnapshotService


class FileService:
    """Centraliza las operaciones de lectura y escritura de archivos en el workspace."""
    @staticmethod
    def tail_audit_lines(limit: int = 200) -> List[str]:
        if not AUDIT_LOG_PATH.exists():
            return []
        # Acquire the RotatingFileHandler lock so reads cannot race with rotation.
        # The handler holds this lock during emit() and doRollover(); by acquiring
        # the same lock here we serialize against both, eliminating the ValueError
        # / OSError window that previously had to be papered over with sleep+retry.
        from tools.gimo_server.security.audit import get_audit_handler
        handler = get_audit_handler()
        with handler.lock:
            return AUDIT_LOG_PATH.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()[-limit:]

    @staticmethod
    def get_file_content(
        target_path: Path,
        start_line: int = 1,
        end_line: int = MAX_LINES,
        token: str = "",
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

    @staticmethod
    def write_file(target_path: Path, content: str, token: str = "SYSTEM") -> str:
        """
        Writes content to a file, creating parent directories if needed.
        Logs the operation in the audit trail.
        """
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            audit_log(
                str(target_path),
                "0",
                content_hash,
                operation="WRITE_FILE",
                actor=token,
            )
            return f"Successfully wrote to {target_path}"
        except Exception as e:
            raise IOError(f"Failed to write to {target_path}: {e}")

    @staticmethod
    def patch_file(target_path: Path, diff: str, token: str = "SYSTEM") -> str:
        """
        Applies a patch to a file. (Placeholder for real diff logic).
        """
        try:
            # In a real impl, we'd use a patch utility
            audit_log(str(target_path), "0", "patch", operation="PATCH_FILE", actor=token)
            return f"Successfully patched {target_path}"
        except Exception as e:
            raise IOError(f"Failed to patch {target_path}: {e}")

    @staticmethod
    def create_dir(target_path: Path, token: str = "SYSTEM") -> str:
        """
        Creates a directory.
        """
        try:
            target_path.mkdir(parents=True, exist_ok=True)
            audit_log(str(target_path), "0", "mkdir", operation="CREATE_DIR", actor=token)
            return f"Successfully created directory {target_path}"
        except Exception as e:
            raise IOError(f"Failed to create directory {target_path}: {e}")
