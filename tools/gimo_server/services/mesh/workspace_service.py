"""
Workspace Service — isolated device sessions for GIMO Mesh.

Enforces invariants:
  INV-L1  No license, no mesh — a GIMO Mesh instance cannot exist without
          a licensed GIMO Core orchestrating it.  License is obtained via
          GIMO Web (Stripe → LicenseGuard).  At boot the server dies if
          invalid; at runtime mesh endpoints verify license is still active.
  INV-W1  Total isolation between workspaces
  INV-W2  A device operates in exactly 1 workspace at a time
  INV-W3  device_mode is per-workspace
  INV-W4  Workspace "default" always exists
  INV-W5  Owner cannot remove themselves
  INV-W6  No Core, no execution — a workspace needs at least one active
          Core device (mode=server|hybrid, connected) for task dispatch.
          Workspace "default" is exempt (central server IS the Core).
  INV-S2  No invitation, no workspace (pairing code required)
  INV-S3  Pairing codes are ephemeral (5 min TTL, single-use)
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from filelock import FileLock

from tools.gimo_server.config import OPS_DATA_DIR
from tools.gimo_server.models.mesh import (
    ConnectionState,
    DeviceMode,
    PairingCode,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)

log = logging.getLogger("gimo.mesh.workspace")

_BASE = Path(OPS_DATA_DIR) / "mesh" / "workspaces"
_LOCK = Path(OPS_DATA_DIR) / "mesh" / ".workspaces.lock"
_PAIRING_TTL_MINUTES = 5
_PAIRING_CODE_LENGTH = 6  # 6-digit numeric code


def _hash_license_key(key: str) -> str:
    """SHA-256 of the license key — never store the raw key."""
    import hashlib
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _get_core_license_hash() -> str:
    """Read the current Core's license key and return its hash.

    Returns empty string if no license is set (debug/test mode).
    """
    import os
    key = os.environ.get("ORCH_LICENSE_KEY", "").strip()
    if not key:
        return ""
    return _hash_license_key(key)


def _safe_id(value: str) -> str:
    """Validate IDs used in file paths — prevent path traversal and collisions.

    Rejects (not strips) any ID containing unsafe characters so that
    two distinct input IDs can never map to the same sanitized output.
    """
    import re
    if not value or not re.fullmatch(r"[a-zA-Z0-9._-]+", value) or value.startswith("."):
        raise ValueError(f"Invalid ID: {value!r}")
    return value


class WorkspaceService:
    def __init__(self) -> None:
        _BASE.mkdir(parents=True, exist_ok=True)
        self._ensure_default()

    # ── Workspace CRUD ──────────────────────────────────────────

    def create_workspace(
        self,
        name: str,
        owner_device_id: str = "",
        license_key_hash: str = "",
    ) -> Workspace:
        workspace_id = f"ws-{uuid.uuid4().hex[:12]}"
        # INV-L1: bind workspace to current Core license
        lk_hash = license_key_hash or _get_core_license_hash()
        ws = Workspace(
            workspace_id=workspace_id,
            name=name,
            owner_device_id=owner_device_id,
            license_key_hash=lk_hash,
        )
        ws_dir = _BASE / workspace_id
        ws_dir.mkdir(parents=True, exist_ok=True)
        (ws_dir / "members").mkdir(exist_ok=True)
        (ws_dir / "pairing").mkdir(exist_ok=True)
        self._save_workspace(ws)

        # Owner is auto-enrolled as member
        if owner_device_id:
            self.add_member(
                workspace_id,
                owner_device_id,
                role=WorkspaceRole.owner,
            )

        log.info("workspace created: %s (%s) owner=%s", workspace_id, name, owner_device_id)
        return ws

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        workspace_id = _safe_id(workspace_id)
        path = _BASE / workspace_id / "workspace.json"
        if not path.exists():
            return None
        return Workspace.model_validate_json(path.read_text(encoding="utf-8"))

    def list_workspaces(self) -> List[Workspace]:
        result = []
        for ws_dir in sorted(_BASE.iterdir()):
            if not ws_dir.is_dir():
                continue
            meta = ws_dir / "workspace.json"
            try:
                if meta.exists():
                    result.append(Workspace.model_validate_json(meta.read_text(encoding="utf-8")))
            except (FileNotFoundError, OSError, ValueError):
                continue  # Concurrent delete or corrupt file — skip
        return result

    def delete_workspace(self, workspace_id: str, registry=None) -> bool:
        """Delete workspace. INV-W4: 'default' cannot be deleted.

        If registry is provided, resets any device whose active_workspace_id
        points to this workspace back to 'default'.
        """
        workspace_id = _safe_id(workspace_id)
        if workspace_id == "default":
            return False
        ws_dir = _BASE / workspace_id
        if not ws_dir.exists():
            return False

        # Reset devices that were in this workspace back to default
        if registry is not None:
            for device in registry.list_devices():
                if device.active_workspace_id == workspace_id:
                    device.active_workspace_id = "default"
                    device.active_task_id = ""
                    registry.save_device(device)
                    log.info("device %s reset to default (workspace %s deleted)", device.device_id, workspace_id)

        import shutil
        shutil.rmtree(ws_dir)
        log.info("workspace deleted: %s", workspace_id)
        return True

    # ── Membership ──────────────────────────────────────────────

    def add_member(
        self,
        workspace_id: str,
        device_id: str,
        role: WorkspaceRole = WorkspaceRole.member,
        device_mode: DeviceMode = DeviceMode.inference,
    ) -> WorkspaceMembership:
        workspace_id, device_id = _safe_id(workspace_id), _safe_id(device_id)
        membership = WorkspaceMembership(
            workspace_id=workspace_id,
            device_id=device_id,
            role=role,
            device_mode=device_mode,
        )
        members_dir = _BASE / workspace_id / "members"
        members_dir.mkdir(parents=True, exist_ok=True)
        path = members_dir / f"{device_id}.json"
        self._atomic_write(path, membership.model_dump_json(indent=2))
        log.info("member added: %s -> workspace %s (role=%s)", device_id, workspace_id, role.value)
        return membership

    def get_member(self, workspace_id: str, device_id: str) -> Optional[WorkspaceMembership]:
        workspace_id, device_id = _safe_id(workspace_id), _safe_id(device_id)
        path = _BASE / workspace_id / "members" / f"{device_id}.json"
        if not path.exists():
            return None
        return WorkspaceMembership.model_validate_json(path.read_text(encoding="utf-8"))

    def list_members(self, workspace_id: str) -> List[WorkspaceMembership]:
        workspace_id = _safe_id(workspace_id)
        members_dir = _BASE / workspace_id / "members"
        if not members_dir.exists():
            return []
        result = []
        for f in sorted(members_dir.glob("*.json")):
            try:
                result.append(WorkspaceMembership.model_validate_json(f.read_text(encoding="utf-8")))
            except (FileNotFoundError, OSError, ValueError):
                continue
        return result

    def remove_member(self, workspace_id: str, device_id: str) -> bool:
        """Remove member. INV-W5: owner cannot remove themselves if last owner."""
        workspace_id, device_id = _safe_id(workspace_id), _safe_id(device_id)
        member = self.get_member(workspace_id, device_id)
        if member is None:
            return False

        if member.role == WorkspaceRole.owner:
            owners = [m for m in self.list_members(workspace_id) if m.role == WorkspaceRole.owner]
            if len(owners) <= 1:
                return False  # INV-W5

        path = _BASE / workspace_id / "members" / f"{device_id}.json"
        path.unlink(missing_ok=True)
        log.info("member removed: %s from workspace %s", device_id, workspace_id)
        return True

    def force_remove_member(self, workspace_id: str, device_id: str) -> bool:
        """Remove member unconditionally — bypasses INV-W5 for device deletion."""
        workspace_id, device_id = _safe_id(workspace_id), _safe_id(device_id)
        path = _BASE / workspace_id / "members" / f"{device_id}.json"
        if not path.exists():
            return False
        path.unlink(missing_ok=True)
        log.info("member force-removed: %s from workspace %s", device_id, workspace_id)
        return True

    def update_member_mode(
        self,
        workspace_id: str,
        device_id: str,
        device_mode: DeviceMode,
    ) -> Optional[WorkspaceMembership]:
        """INV-W3: device_mode is per-workspace."""
        workspace_id, device_id = _safe_id(workspace_id), _safe_id(device_id)
        member = self.get_member(workspace_id, device_id)
        if member is None:
            return None
        member.device_mode = device_mode
        path = _BASE / workspace_id / "members" / f"{device_id}.json"
        self._atomic_write(path, member.model_dump_json(indent=2))
        return member

    def get_device_workspaces(self, device_id: str) -> List[WorkspaceMembership]:
        """List all workspaces a device belongs to."""
        device_id = _safe_id(device_id)
        result = []
        for ws_dir in _BASE.iterdir():
            if not ws_dir.is_dir():
                continue
            member_file = ws_dir / "members" / f"{device_id}.json"
            try:
                if member_file.exists():
                    result.append(WorkspaceMembership.model_validate_json(member_file.read_text(encoding="utf-8")))
            except (FileNotFoundError, OSError, ValueError):
                continue
        return result

    # ── INV-L1 — License binding ─────────────────────────────────

    def is_workspace_licensed(self, workspace_id: str) -> bool:
        """INV-L1: verify workspace is bound to the current Core's license.

        Returns True if:
          - workspace is 'default' (always valid — inherits Core's boot license)
          - workspace has no hash (legacy/test — allow)
          - workspace hash matches current Core's license hash
          - Core has no license key set (debug/test mode — allow)

        Returns False (blocked, not deleted) if the hash doesn't match.
        """
        if workspace_id == "default":
            return True
        ws = self.get_workspace(workspace_id)
        if ws is None:
            return False
        # No hash stored → legacy workspace, allow
        if not ws.license_key_hash:
            return True
        core_hash = _get_core_license_hash()
        # No license on Core → debug/test mode, allow
        if not core_hash:
            return True
        return ws.license_key_hash == core_hash

    # ── INV-W6 — Core presence ─────────────────────────────────

    def has_active_core(self, workspace_id: str, registry) -> bool:
        """INV-W6: workspace must have at least one active Core device.

        A Core device is one with mode=server or mode=hybrid and
        connection_state=connected.  Workspace 'default' always returns
        True because the central GIMO server IS the Core.
        """
        if workspace_id == "default":
            return True

        members = self.list_members(workspace_id)
        for member in members:
            if member.device_mode not in (DeviceMode.server, DeviceMode.hybrid):
                continue
            device = registry.get_device(member.device_id)
            if device and device.connection_state == ConnectionState.connected:
                return True
        return False

    # ── Pairing Codes ───────────────────────────────────────────

    def generate_pairing_code(self, workspace_id: str) -> Optional[PairingCode]:
        """Generate 6-digit pairing code. INV-S3: 5 min TTL, single-use."""
        if not self.get_workspace(workspace_id):
            return None

        with FileLock(str(_LOCK), timeout=5):
            # Purge expired codes first
            self._purge_expired_codes(workspace_id)

            code = "".join([str(secrets.randbelow(10)) for _ in range(_PAIRING_CODE_LENGTH)])
            now = datetime.now(timezone.utc)
            pairing = PairingCode(
                code=code,
                workspace_id=workspace_id,
                created_at=now,
                expires_at=now + timedelta(minutes=_PAIRING_TTL_MINUTES),
            )
            pairing_dir = _BASE / workspace_id / "pairing"
            pairing_dir.mkdir(parents=True, exist_ok=True)
            path = pairing_dir / f"{code}.json"
            self._atomic_write(path, pairing.model_dump_json(indent=2))
            log.info("pairing code generated for workspace %s (expires in %d min)", workspace_id, _PAIRING_TTL_MINUTES)
            return pairing

    def join_with_code(
        self,
        code: str,
        device_id: str,
        device_mode: DeviceMode = DeviceMode.inference,
    ) -> Optional[WorkspaceMembership]:
        """
        Join workspace via pairing code.
        INV-S2: No invitation, no workspace.
        INV-S3: Expired/used codes are rejected.
        """
        # Sanitize code — only 6-digit numeric allowed (prevent path traversal)
        if not code or not code.isdigit() or len(code) != _PAIRING_CODE_LENGTH:
            return None
        with FileLock(str(_LOCK), timeout=5):
            # Search for the code across all workspaces
            pairing = self._find_pairing_code(code)
            if pairing is None:
                return None

            now = datetime.now(timezone.utc)
            if pairing.used or pairing.expires_at < now:
                return None

            # Check device not already member
            existing = self.get_member(pairing.workspace_id, device_id)
            if existing:
                # Still consume the code to prevent probing
                pairing.used = True
                pairing.used_by = device_id
                pairing_path = _BASE / pairing.workspace_id / "pairing" / f"{code}.json"
                self._atomic_write(pairing_path, pairing.model_dump_json(indent=2))
                return existing

            # Add member FIRST — if this fails, code stays valid for retry
            membership = self.add_member(
                pairing.workspace_id,
                device_id,
                role=WorkspaceRole.member,
                device_mode=device_mode,
            )

            # Mark code as used AFTER successful membership
            pairing.used = True
            pairing.used_by = device_id
            pairing_path = _BASE / pairing.workspace_id / "pairing" / f"{code}.json"
            self._atomic_write(pairing_path, pairing.model_dump_json(indent=2))

            return membership

    # ── Internal ────────────────────────────────────────────────

    def _ensure_default(self) -> None:
        """INV-W4: Workspace 'default' always exists."""
        default_dir = _BASE / "default"
        if not default_dir.exists():
            default_dir.mkdir(parents=True, exist_ok=True)
            (default_dir / "members").mkdir(exist_ok=True)
            (default_dir / "pairing").mkdir(exist_ok=True)
            ws = Workspace(
                workspace_id="default",
                name="Default",
            )
            self._save_workspace(ws)
            log.info("default workspace created")

    def _save_workspace(self, ws: Workspace) -> None:
        path = _BASE / ws.workspace_id / "workspace.json"
        self._atomic_write(path, ws.model_dump_json(indent=2))

    def _find_pairing_code(self, code: str) -> Optional[PairingCode]:
        for ws_dir in _BASE.iterdir():
            if not ws_dir.is_dir():
                continue
            path = ws_dir / "pairing" / f"{code}.json"
            if path.exists():
                return PairingCode.model_validate_json(path.read_text(encoding="utf-8"))
        return None

    def _purge_expired_codes(self, workspace_id: str) -> int:
        """INV-S3: purge expired codes on every request."""
        pairing_dir = _BASE / workspace_id / "pairing"
        if not pairing_dir.exists():
            return 0
        now = datetime.now(timezone.utc)
        purged = 0
        for f in pairing_dir.glob("*.json"):
            try:
                pc = PairingCode.model_validate_json(f.read_text(encoding="utf-8"))
                if pc.expires_at < now or pc.used:
                    f.unlink()
                    purged += 1
            except Exception:
                f.unlink()
                purged += 1
        return purged

    @staticmethod
    def _atomic_write(path: Path, data: str) -> None:
        """INV-P1: atomic writes via tempfile + rename."""
        import os
        import tempfile
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp",
        )
        fd_closed = False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                fd_closed = True  # fdopen adopted fd; with-block will close it
                f.write(data)
            Path(tmp_path).replace(path)
        except Exception:
            if not fd_closed:
                try:
                    os.close(fd)
                except OSError:
                    pass
            Path(tmp_path).unlink(missing_ok=True)
            raise
