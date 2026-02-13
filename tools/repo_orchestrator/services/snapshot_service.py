import os
import time
import shutil
import hashlib
from pathlib import Path
from tools.repo_orchestrator.config import SNAPSHOT_DIR, SNAPSHOT_TTL

class SnapshotService:
    @staticmethod
    def ensure_snapshot_dir():
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def create_snapshot(target_path: Path) -> Path:
        snapshot_filename = f"{hashlib.sha256(str(target_path).encode()).hexdigest()[:12]}_{target_path.name}"
        snapshot_path = SNAPSHOT_DIR / snapshot_filename
        shutil.copy2(target_path, snapshot_path)
        return snapshot_path

    @staticmethod
    def cleanup_old_snapshots():
        now = time.time()
        if not SNAPSHOT_DIR.exists():
            return
        for item in SNAPSHOT_DIR.iterdir():
            if item.is_file() and now - item.stat().st_mtime > SNAPSHOT_TTL:
                try:
                    item.unlink()
                except Exception:
                    pass
