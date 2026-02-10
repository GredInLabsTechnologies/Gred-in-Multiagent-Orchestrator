import hashlib
import os
import shutil
import time
from pathlib import Path

from tools.gimo_server.config import SNAPSHOT_DIR, SNAPSHOT_TTL


class SnapshotService:
    @staticmethod
    def ensure_snapshot_dir():
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        # Verify/Set permissions to 700 (User only) for privacy
        try:
            SNAPSHOT_DIR.chmod(0o700)
        except Exception:
            # Best-effort permissions on Windows; ignore failures.
            pass

    @staticmethod
    def create_snapshot(target_path: Path) -> Path:
        # Create a unique snapshot for this specific read event (Forensic Integrity)
        # Includes timestamp to prevent collisions and allow historical reconstruction within TTL
        timestamp = int(time.time() * 1000)
        path_hash = hashlib.sha256(str(target_path).encode()).hexdigest()[:12]
        snapshot_filename = f"{timestamp}_{path_hash}_{target_path.name}"
        snapshot_path = SNAPSHOT_DIR / snapshot_filename

        # Atomic copy preserving stats
        shutil.copy2(target_path, snapshot_path)
        return snapshot_path

    @staticmethod
    def secure_delete(path: Path):
        """
        Securely deletes a file by overwriting it with zeros before unlinking.
        """
        try:
            if path.is_file():
                # 1. Get size
                size = path.stat().st_size

                # 2. Overwrite with zeros and flush in single open
                with open(path, "r+b") as f:
                    f.write(b"\0" * size)
                    f.flush()
                    os.fsync(f.fileno())

            # 3. Unlink
            path.unlink(missing_ok=True)
        except Exception:
            # Fallback to standard unlink on error to ensure removal at least
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    @staticmethod
    def cleanup_old_snapshots():
        now = time.time()
        if not SNAPSHOT_DIR.exists():
            return
        for item in SNAPSHOT_DIR.iterdir():
            if item.is_file() and now - item.stat().st_mtime > SNAPSHOT_TTL:
                SnapshotService.secure_delete(item)
