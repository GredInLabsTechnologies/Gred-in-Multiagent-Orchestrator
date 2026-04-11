"""Onboarding Service — zero-ADB device enrollment via 6-digit codes.

Bridges the auth chicken-and-egg: new devices have no bearer token, but all
mesh endpoints require one.  The onboarding code IS the authentication for
the initial claim.

Flow:
  1. Admin generates code  → POST /ops/mesh/onboard/code  (auth required)
  2. Device redeems code   → POST /ops/mesh/onboard/redeem (NO auth)
  3. Device receives bearer_token (device_secret) for all future requests
  4. Device enters pending_approval → admin approves → mesh operational

Security:
  - 6-digit numeric = 1M combinations
  - 5-min TTL + single-use
  - Rate-limited: 5 attempts/min per IP on redeem endpoint
  - Code consumed even on failure (anti-brute-force after 3 bad attempts)
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from filelock import FileLock
from pydantic import BaseModel, Field

from ...config import OPS_DATA_DIR
from ...models.mesh import DeviceMode

logger = logging.getLogger("orchestrator.mesh.onboarding")

_BASE = Path(OPS_DATA_DIR) / "mesh" / "onboard_codes"
_LOCK = Path(OPS_DATA_DIR) / "mesh" / ".onboard.lock"
_CODE_LENGTH = 6
_CODE_TTL_MINUTES = 5


class OnboardingCode(BaseModel):
    """Ephemeral 6-digit code that maps to an enrollment + workspace join."""
    code: str
    workspace_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    used: bool = False
    used_by: Optional[str] = None


class OnboardResult(BaseModel):
    """Returned to the device after successful redeem."""
    device_id: str
    bearer_token: str
    workspace_id: str
    workspace_name: str
    status: str = "pending_approval"


class OnboardingService:
    """Generates and redeems 6-digit onboarding codes."""

    def __init__(self) -> None:
        _BASE.mkdir(parents=True, exist_ok=True)

    def _lock(self) -> FileLock:
        return FileLock(str(_LOCK), timeout=5)

    # ── Code generation (admin) ─────────────────────────────────

    def create_code(self, workspace_id: str = "default") -> OnboardingCode:
        """Generate a 6-digit code bound to a workspace. TTL = 5 min."""
        now = datetime.now(timezone.utc)
        code_str = "".join(str(secrets.randbelow(10)) for _ in range(_CODE_LENGTH))

        oc = OnboardingCode(
            code=code_str,
            workspace_id=workspace_id,
            created_at=now,
            expires_at=now + timedelta(minutes=_CODE_TTL_MINUTES),
        )

        with self._lock():
            # Purge expired codes first
            self._purge_expired()
            self._save_code(oc)

        logger.info("Onboarding code generated for workspace=%s (expires %d min)", workspace_id, _CODE_TTL_MINUTES)
        return oc

    # ── Code redemption (unauthenticated) ───────────────────────

    def redeem_code(
        self,
        code: str,
        device_id: str,
        name: str = "",
        device_mode: DeviceMode = DeviceMode.inference,
        device_class: str = "smartphone",
    ) -> Optional[OnboardResult]:
        """Redeem a 6-digit code to enroll a device and join a workspace.

        Returns OnboardResult with bearer_token on success, None on failure.
        The code is consumed even on failure (anti-brute-force).
        """
        # Validate code format
        if not code or not code.isdigit() or len(code) != _CODE_LENGTH:
            return None

        with self._lock():
            oc = self._load_code(code)
            if oc is None:
                return None

            # Already used? Reject.
            if oc.used:
                logger.warning("Onboarding code already used (by=%s)", oc.used_by)
                return None

            # Always consume to prevent probing
            oc.used = True
            oc.used_by = device_id
            self._save_code(oc)

            # Validate expiry
            if datetime.now(timezone.utc) > oc.expires_at:
                logger.warning("Onboarding code expired for device=%s", device_id)
                return None

            # Enroll device via registry
            from .registry import MeshRegistry
            registry = MeshRegistry()
            existing = registry.get_device(device_id)
            if existing is not None:
                logger.warning("Device %s already enrolled — returning existing secret", device_id)
                # Return existing device's secret as bearer token
                return OnboardResult(
                    device_id=device_id,
                    bearer_token=existing.device_secret,
                    workspace_id=oc.workspace_id,
                    workspace_name=self._get_workspace_name(oc.workspace_id),
                    status=existing.connection_state.value,
                )

            device = registry.enroll_device(
                device_id=device_id,
                name=name,
                device_mode=device_mode,
                device_class=device_class,
            )

            # Join workspace
            from .workspace_service import WorkspaceService
            ws_svc = WorkspaceService()
            ws_svc.add_member(oc.workspace_id, device_id, device_mode=device_mode)

            logger.info("Device %s onboarded via code → workspace=%s", device_id, oc.workspace_id)

            return OnboardResult(
                device_id=device_id,
                bearer_token=device.device_secret,
                workspace_id=oc.workspace_id,
                workspace_name=self._get_workspace_name(oc.workspace_id),
                status="pending_approval",
            )

    # ── Internal ────────────────────────────────────────────────

    def _code_path(self, code: str) -> Path:
        return _BASE / f"{code}.json"

    def _save_code(self, oc: OnboardingCode) -> None:
        path = self._code_path(oc.code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            oc.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _load_code(self, code: str) -> Optional[OnboardingCode]:
        path = self._code_path(code)
        if not path.exists():
            return None
        try:
            return OnboardingCode.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _purge_expired(self) -> int:
        """Remove expired and used codes."""
        now = datetime.now(timezone.utc)
        purged = 0
        for f in _BASE.glob("*.json"):
            try:
                oc = OnboardingCode.model_validate_json(f.read_text(encoding="utf-8"))
                if oc.used or now > oc.expires_at:
                    f.unlink(missing_ok=True)
                    purged += 1
            except Exception:
                f.unlink(missing_ok=True)
                purged += 1
        return purged

    @staticmethod
    def _get_workspace_name(workspace_id: str) -> str:
        from .workspace_service import WorkspaceService
        ws_svc = WorkspaceService()
        ws = ws_svc.get_workspace(workspace_id)
        return ws.name if ws else workspace_id
