"""OPS service control endpoints — migrated from legacy /ui/service/*."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ...models import ServiceStatusResponse
from ...security import check_rate_limit
from ...security.auth import AuthContext
from ...services.system_service import SystemService
from ..ops.common import require_read, require_operator

router = APIRouter(prefix="/ops/service", tags=["service"])


@router.get("/status", response_model=ServiceStatusResponse)
def get_service_status(
    auth: Annotated[AuthContext, Depends(require_read)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    return {"status": SystemService.get_status()}


@router.post("/restart")
def restart_service(
    auth: Annotated[AuthContext, Depends(require_operator)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    success = SystemService.restart(actor=auth.token)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to restart service")
    return {"status": "restarting"}


@router.post("/stop")
def stop_service(
    auth: Annotated[AuthContext, Depends(require_operator)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    success = SystemService.stop(actor=auth.token)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop service")
    return {"status": "stopping"}
