from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from tools.gimo_server.config import OPS_DATA_DIR
from tools.gimo_server.security.audit import audit_log

logger = logging.getLogger("orchestrator.repo_override")


class RepoOverrideService:
    """Persistence + concurrency control for human repo override (Phase 5)."""

    OVERRIDE_PATH: Path = OPS_DATA_DIR / "state" / "active_repo.json"
    DEFAULT_TTL_SECONDS = 24 * 60 * 60

    @classmethod
    def _ensure_parent_dir(cls) -> None:
        cls.OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _iso(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _parse_iso(value: str | None) -> Optional[datetime]:
        if not value or not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    @staticmethod
    def _canonical_json(data: dict[str, Any]) -> str:
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def _compute_etag(cls, payload_without_etag: dict[str, Any]) -> str:
        digest = hashlib.sha256(cls._canonical_json(payload_without_etag).encode("utf-8")).hexdigest()
        return f'"{digest}"'

    @classmethod
    def _atomic_write(cls, payload: dict[str, Any]) -> None:
        cls._ensure_parent_dir()
        tmp_path = cls.OVERRIDE_PATH.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(cls.OVERRIDE_PATH)

    @classmethod
    def _read_raw(cls) -> Optional[dict[str, Any]]:
        if not cls.OVERRIDE_PATH.exists():
            return None
        try:
            data = json.loads(cls.OVERRIDE_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return data
        except Exception as exc:
            logger.warning("Invalid repo override file at %s: %s", cls.OVERRIDE_PATH, exc)
            return None

    @classmethod
    def _delete_file(cls) -> None:
        try:
            if cls.OVERRIDE_PATH.exists():
                cls.OVERRIDE_PATH.unlink()
        except Exception as exc:
            logger.warning("Failed deleting override file %s: %s", cls.OVERRIDE_PATH, exc)

    @classmethod
    def get_active_override(cls) -> Optional[dict[str, Any]]:
        raw = cls._read_raw()
        if not raw:
            return None
        expires_dt = cls._parse_iso(raw.get("expires_at"))
        if not expires_dt or expires_dt <= cls._utcnow():
            cls._delete_file()
            audit_log(
                "REPO_OVERRIDE",
                "EXPIRED",
                str(raw.get("repo_id", "")),
                operation="repo_override_expired",
                actor="system",
            )
            return None
        return raw

    @classmethod
    def set_human_override(
        cls,
        *,
        repo_id: str,
        set_by_user: str,
        source: str = "ui",
        reason: str = "",
        if_match_etag: str | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        existing = cls.get_active_override()
        existing_etag = existing.get("etag") if existing else None

        if existing and if_match_etag != existing_etag:
            raise ValueError("OVERRIDE_ETAG_MISMATCH")

        now = cls._utcnow()
        expires_dt = cls._parse_iso(expires_at) if expires_at else now + timedelta(seconds=cls.DEFAULT_TTL_SECONDS)
        if not expires_dt or expires_dt <= now:
            expires_dt = now + timedelta(seconds=cls.DEFAULT_TTL_SECONDS)

        payload_without_etag = {
            "repo_id": repo_id,
            "set_by_user": set_by_user,
            "set_at": cls._iso(now),
            "expires_at": cls._iso(expires_dt),
            "reason": reason,
            "source": source,
            "version": 1,
        }
        etag = cls._compute_etag(payload_without_etag)
        payload = {**payload_without_etag, "etag": etag}
        cls._atomic_write(payload)

        audit_log(
            "REPO_OVERRIDE",
            "SET" if not existing else "UPDATE",
            repo_id,
            operation="repo_override_set" if not existing else "repo_override_updated",
            actor=set_by_user,
        )
        return payload

    @classmethod
    def revoke_human_override(cls, *, actor: str, if_match_etag: str | None = None) -> bool:
        existing = cls.get_active_override()
        if not existing:
            return False

        if if_match_etag != existing.get("etag"):
            raise ValueError("OVERRIDE_ETAG_MISMATCH")

        repo_id = str(existing.get("repo_id", ""))
        cls._delete_file()
        audit_log(
            "REPO_OVERRIDE",
            "REVOKE",
            repo_id,
            operation="repo_override_revoked",
            actor=actor,
        )
        return True
