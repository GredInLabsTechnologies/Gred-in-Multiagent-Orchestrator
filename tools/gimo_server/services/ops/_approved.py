from __future__ import annotations

import logging
from typing import List, Optional

from ...ops_models import OpsApproved

logger = logging.getLogger("orchestrator.ops")


class ApprovedMixin:
    """Approved-entry read operations."""

    @classmethod
    def list_approved(cls) -> List[OpsApproved]:
        if not cls.APPROVED_DIR.exists():
            return []
        out: List[OpsApproved] = []
        for f in cls.APPROVED_DIR.glob(cls._APPROVED_GLOB):
            try:
                out.append(OpsApproved.model_validate_json(f.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.warning("Failed to parse approved %s: %s", f.name, exc)
        return sorted(out, key=lambda a: a.approved_at, reverse=True)

    @classmethod
    def get_approved(cls, approved_id: str) -> Optional[OpsApproved]:
        f = cls._approved_path(approved_id)
        if not f.exists():
            return None
        return OpsApproved.model_validate_json(f.read_text(encoding="utf-8"))
