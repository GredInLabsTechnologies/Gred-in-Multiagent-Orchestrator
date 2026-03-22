"""OPS security endpoints — migrated from legacy /ui/security/*."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...security.auth import AuthContext
from ..ops.common import require_read, require_operator

router = APIRouter(prefix="/ops/security", tags=["security"])


@router.get("/events")
def get_security_events(auth: AuthContext = Depends(require_read)):
    from ...security import threat_engine
    return threat_engine.snapshot()


@router.post("/resolve")
def resolve_security(
    action: str = "clear_all",
    auth: AuthContext = Depends(require_operator),
):
    from ...security import save_security_db, threat_engine

    if action == "clear_all":
        threat_engine.clear_all()
    elif action == "downgrade":
        threat_engine.downgrade()
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    save_security_db()

    return {
        "status": "success",
        "action": action,
        "new_level": threat_engine.level_label,
        "message": f"Threat level set to {threat_engine.level_label}",
    }
