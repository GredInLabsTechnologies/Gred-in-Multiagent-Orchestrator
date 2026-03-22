from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict

from ._base import _utcnow, _json_dump

logger = logging.getLogger("orchestrator.ops")


class LockMixin:
    """Merge lock acquire / release / heartbeat / recovery."""

    @classmethod
    def recover_stale_lock(cls, repo_id: str) -> bool:
        """Remove a merge lock that is past its TTL.

        Returns True when a stale lock was removed, else False.
        """
        lock_path = cls._merge_lock_path(repo_id)
        if not lock_path.exists():
            return False
        try:
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            expires_str = str(data.get("expires_at") or "")
            if expires_str:
                expires = datetime.fromisoformat(expires_str)
                if _utcnow() > expires:
                    lock_path.unlink(missing_ok=True)
                    logger.info("Recovered stale merge lock for repo=%s", repo_id)
                    return True
        except Exception as exc:
            logger.warning("recover_stale_lock error for repo=%s: %s", repo_id, exc)
        return False

    @classmethod
    def acquire_merge_lock(cls, repo_id: str, run_id: str, *, ttl_seconds: int = 120) -> Dict[str, Any]:
        """Acquire a file-based merge lock. Raises RuntimeError if already locked."""
        lock_path = cls._merge_lock_path(repo_id)
        expires_at = _utcnow() + timedelta(seconds=ttl_seconds)
        with cls._lock():
            if lock_path.exists():
                try:
                    data = json.loads(lock_path.read_text(encoding="utf-8"))
                    expires_str = str(data.get("expires_at") or "")
                    if expires_str:
                        expires = datetime.fromisoformat(expires_str)
                        if _utcnow() <= expires:
                            raise RuntimeError(
                                f"Merge lock held by run={data.get('run_id')} until {expires_str}"
                            )
                except RuntimeError:
                    raise
                except Exception:
                    pass  # Corrupt lock file — overwrite it
            lock_id = f"lock_{os.urandom(4).hex()}"
            payload: Dict[str, Any] = {
                "lock_id": lock_id,
                "run_id": run_id,
                "repo_id": repo_id,
                "expires_at": expires_at.isoformat(),
            }
            lock_path.write_text(_json_dump(payload), encoding="utf-8")
        return payload

    @classmethod
    def release_merge_lock(cls, repo_id: str, run_id: str) -> None:
        """Release the merge lock if it is held by this run."""
        lock_path = cls._merge_lock_path(repo_id)
        if not lock_path.exists():
            return
        try:
            with cls._lock():
                data = json.loads(lock_path.read_text(encoding="utf-8"))
                if data.get("run_id") == run_id:
                    lock_path.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("release_merge_lock error for repo=%s: %s", repo_id, exc)

    @classmethod
    def heartbeat_merge_lock(cls, repo_id: str, run_id: str, *, ttl_seconds: int = 120) -> Dict[str, Any]:
        """Extend the TTL of the merge lock held by this run."""
        lock_path = cls._merge_lock_path(repo_id)
        if not lock_path.exists():
            raise RuntimeError(f"No merge lock found for repo={repo_id}")
        with cls._lock():
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            if data.get("run_id") != run_id:
                raise RuntimeError(
                    f"Merge lock held by run={data.get('run_id')}, not {run_id}"
                )
            data["expires_at"] = (_utcnow() + timedelta(seconds=ttl_seconds)).isoformat()
            lock_path.write_text(_json_dump(data), encoding="utf-8")
            return data
