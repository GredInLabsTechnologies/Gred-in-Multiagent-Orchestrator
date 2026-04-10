"""Structured audit log for GIMO Mesh operations.

Provides receipt correlation, event tracking, and audit trail
for all mesh operations (enrollment, dispatch, thermal, state changes).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from filelock import FileLock

from ...config import OPS_DATA_DIR

logger = logging.getLogger("orchestrator.mesh.audit")

_MESH_DIR = OPS_DATA_DIR / "mesh"
_AUDIT_LOG = _MESH_DIR / "audit.jsonl"
_LOCK_FILE = _MESH_DIR / ".audit.lock"

AuditCategory = Literal[
    "enrollment",
    "connection",
    "dispatch",
    "thermal",
    "execution",
    "control",
    "config",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MeshAuditService:
    """Append-only structured audit log for mesh operations."""

    def __init__(self) -> None:
        _MESH_DIR.mkdir(parents=True, exist_ok=True)

    def _lock(self) -> FileLock:
        return FileLock(str(_LOCK_FILE), timeout=5)

    def record(
        self,
        category: AuditCategory,
        action: str,
        device_id: str = "",
        task_id: str = "",
        receipt_id: str = "",
        actor: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a structured audit entry."""
        entry = {
            "timestamp": _utcnow().isoformat(),
            "category": category,
            "action": action,
            "device_id": device_id,
            "task_id": task_id,
            "receipt_id": receipt_id,
            "actor": actor,
            "details": details or {},
        }
        with self._lock():
            with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")

    def query(
        self,
        category: Optional[str] = None,
        device_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query audit log with optional filters."""
        if not _AUDIT_LOG.exists():
            return []

        entries: List[Dict[str, Any]] = []
        for line in _AUDIT_LOG.read_text(encoding="utf-8").strip().splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if category and entry.get("category") != category:
                continue
            if device_id and entry.get("device_id") != device_id:
                continue
            if task_id and entry.get("task_id") != task_id:
                continue
            entries.append(entry)

        return entries[-limit:]

    def correlate_receipt(self, receipt_id: str) -> List[Dict[str, Any]]:
        """Find all audit entries related to a receipt."""
        if not _AUDIT_LOG.exists():
            return []

        entries: List[Dict[str, Any]] = []
        for line in _AUDIT_LOG.read_text(encoding="utf-8").strip().splitlines():
            try:
                entry = json.loads(line)
                if entry.get("receipt_id") == receipt_id:
                    entries.append(entry)
            except json.JSONDecodeError:
                continue
        return entries
