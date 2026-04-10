"""Device enrollment flow with time-limited tokens and anti-replay."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from filelock import FileLock

from ...config import OPS_DATA_DIR
from ...models.mesh import DeviceMode, EnrollmentToken, MeshDeviceInfo
from .registry import MeshRegistry

logger = logging.getLogger("orchestrator.mesh.enrollment")

_MESH_DIR = OPS_DATA_DIR / "mesh"
_TOKENS_DIR = _MESH_DIR / "tokens"
_LOCK_FILE = _MESH_DIR / ".enrollment.lock"

DEFAULT_TOKEN_TTL_MINUTES = 15


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EnrollmentService:
    """Manages enrollment tokens and the device claim flow.

    Flow:
    1. Admin creates enrollment token (time-limited, single-use)
    2. Device agent claims token with its device_id + metadata
    3. Device enters pending_approval state
    4. Admin approves or refuses the device
    """

    def __init__(self, registry: MeshRegistry) -> None:
        self._registry = registry
        _TOKENS_DIR.mkdir(parents=True, exist_ok=True)

    def _lock(self) -> FileLock:
        return FileLock(str(_LOCK_FILE), timeout=5)

    # ── Token management ─────────────────────────────────────

    def create_token(self, ttl_minutes: int = DEFAULT_TOKEN_TTL_MINUTES) -> EnrollmentToken:
        now = _utcnow()
        token = EnrollmentToken(
            token=secrets.token_urlsafe(32),
            created_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
            used=False,
        )
        self._save_token(token)
        logger.info("Created enrollment token (expires in %d min)", ttl_minutes)
        return token

    def list_tokens(self) -> List[EnrollmentToken]:
        tokens: List[EnrollmentToken] = []
        for p in sorted(_TOKENS_DIR.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                tokens.append(EnrollmentToken(**data))
            except Exception:
                continue
        return tokens

    def revoke_token(self, token_str: str) -> bool:
        path = self._token_path(token_str)
        if path.exists():
            with self._lock():
                path.unlink()
            logger.info("Revoked enrollment token")
            return True
        return False

    # ── Claim flow ───────────────────────────────────────────

    def claim(
        self,
        token_str: str,
        device_id: str,
        name: str = "",
        device_mode: DeviceMode = DeviceMode.inference,
        device_class: str = "desktop",
    ) -> MeshDeviceInfo:
        """Device claims an enrollment token.

        Validates token, marks as used, enrolls device in pending_approval.
        Anti-replay: token can only be used once.
        """
        with self._lock():
            # All validation inside lock to prevent TOCTOU race
            token = self._load_token(token_str)
            if token is None:
                raise ValueError("Invalid enrollment token")

            if token.used:
                raise ValueError("Enrollment token already used (anti-replay)")

            if _utcnow() > token.expires_at:
                raise ValueError("Enrollment token expired")

            # Check device not already enrolled
            existing = self._registry.get_device(device_id)
            if existing is not None:
                raise ValueError(f"Device {device_id} already enrolled")

            # Mark token as used
            token.used = True
            token.device_id = device_id
            self._save_token(token)

        # Enroll device
        device = self._registry.enroll_device(
            device_id=device_id,
            name=name,
            device_mode=device_mode,
            device_class=device_class,
        )
        logger.info("Device %s claimed token and enrolled", device_id)
        return device

    # ── Internal ─────────────────────────────────────────────

    def _token_path(self, token_str: str) -> Path:
        # Hash token for filename to avoid path injection
        h = hashlib.sha256(token_str.encode()).hexdigest()[:16]
        return _TOKENS_DIR / f"enroll_{h}.json"

    def _save_token(self, token: EnrollmentToken) -> None:
        path = self._token_path(token.token)
        path.write_text(
            json.dumps(token.model_dump(mode="json"), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_token(self, token_str: str) -> Optional[EnrollmentToken]:
        path = self._token_path(token_str)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return EnrollmentToken(**data)
        except Exception:
            return None
