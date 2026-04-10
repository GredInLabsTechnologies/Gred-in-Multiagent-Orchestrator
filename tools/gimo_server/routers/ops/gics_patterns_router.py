"""
GICS Task Patterns Router — Phase 2.

CRUD endpoints for GICS task patterns used by GIMO Mesh.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext

from .common import _actor_label, _require_role

router = APIRouter(prefix="/ops/gics/patterns", tags=["gics-patterns"])
logger = logging.getLogger("orchestrator.routers.ops.gics_patterns")


def _get_gics(request: Request):
    gics = getattr(request.app.state, "gics", None)
    if gics is None:
        raise HTTPException(503, detail="GICS service not initialized")
    return gics


@router.get("")
async def list_patterns(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> List[Dict[str, Any]]:
    _require_role(auth, "operator")
    gics = _get_gics(request)
    return gics.get_task_patterns()


@router.get("/{task_type}")
async def get_pattern(
    task_type: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    model_id: Annotated[Optional[str], Query()] = None,
) -> Dict[str, Any]:
    _require_role(auth, "operator")
    gics = _get_gics(request)
    result = gics.query_task_pattern(task_type, model_id=model_id or "")
    if result is None:
        raise HTTPException(404, detail=f"No pattern found for task_type={task_type}")
    return result
