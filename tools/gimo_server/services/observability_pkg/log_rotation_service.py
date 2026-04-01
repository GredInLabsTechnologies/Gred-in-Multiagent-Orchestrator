"""Log rotation service — manages log file lifecycle.

Runs on startup and periodically to:
- Compress files > 50MB
- Delete files with mtime > 30 days
- Archive terminal runs with mtime > 7 days
"""

from __future__ import annotations

import gzip
import logging
import shutil
import time
from pathlib import Path

from ...config import OPS_DATA_DIR

logger = logging.getLogger("orchestrator.log_rotation")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_AGE_DAYS = 30
ARCHIVE_AGE_DAYS = 7

SCAN_DIRS = [
    OPS_DATA_DIR / "run_logs",
    OPS_DATA_DIR / "run_events",
    OPS_DATA_DIR / "logs",
]


class LogRotationService:
    """Manages log file rotation, compression, and cleanup."""

    @classmethod
    def run_rotation(cls) -> dict:
        """Execute a full rotation pass. Returns stats."""
        stats = {"compressed": 0, "deleted": 0, "archived": 0, "errors": 0}

        for scan_dir in SCAN_DIRS:
            if not scan_dir.exists():
                continue
            cls._process_directory(scan_dir, stats)

        # Archive old terminal runs
        runs_dir = OPS_DATA_DIR / "runs"
        if runs_dir.exists():
            cls._archive_old_runs(runs_dir, stats)

        if any(v > 0 for v in stats.values()):
            logger.info("Log rotation: %s", stats)
        return stats

    @classmethod
    def _process_directory(cls, directory: Path, stats: dict) -> None:
        for file_path in directory.iterdir():
            if not file_path.is_file():
                continue
            if file_path.suffix == ".gz":
                continue

            try:
                file_stat = file_path.stat()
                age_days = (time.time() - file_stat.st_mtime) / 86400

                # Delete old files
                if age_days > MAX_AGE_DAYS:
                    file_path.unlink(missing_ok=True)
                    stats["deleted"] += 1
                    logger.debug("Deleted old file: %s (%.0f days)", file_path.name, age_days)
                    continue

                # Compress large files
                if file_stat.st_size > MAX_FILE_SIZE:
                    cls._compress_file(file_path)
                    stats["compressed"] += 1
            except Exception as exc:
                logger.warning("Log rotation error for %s: %s", file_path, exc)
                stats["errors"] += 1

    @classmethod
    def _compress_file(cls, file_path: Path) -> None:
        gz_path = file_path.with_suffix(file_path.suffix + ".gz")
        tmp_path = gz_path.with_suffix(".tmp")
        try:
            with open(file_path, "rb") as f_in, gzip.open(tmp_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            tmp_path.rename(gz_path)
            # Truncate original to keep recent entries
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("")
            logger.info("Compressed %s -> %s", file_path.name, gz_path.name)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    @classmethod
    def _archive_old_runs(cls, runs_dir: Path, stats: dict) -> None:
        archive_dir = OPS_DATA_DIR / "archive" / "runs"
        terminal_statuses = {"done", "error", "cancelled", "ROLLBACK_EXECUTED"}

        for run_file in runs_dir.glob("r_*.json"):
            try:
                age_days = (time.time() - run_file.stat().st_mtime) / 86400
                if age_days <= ARCHIVE_AGE_DAYS:
                    continue

                import json
                data = json.loads(run_file.read_text(encoding="utf-8"))
                if data.get("status") not in terminal_statuses:
                    continue

                archive_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(run_file), str(archive_dir / run_file.name))
                stats["archived"] += 1

                # Also move corresponding log
                log_file = OPS_DATA_DIR / "run_logs" / f"{run_file.stem}.jsonl"
                if log_file.exists():
                    (archive_dir.parent / "run_logs").mkdir(parents=True, exist_ok=True)
                    shutil.move(str(log_file), str(archive_dir.parent / "run_logs" / log_file.name))
            except Exception as exc:
                logger.warning("Archive error for %s: %s", run_file, exc)
                stats["errors"] += 1
