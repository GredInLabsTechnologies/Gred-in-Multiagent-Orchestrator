"""Core endpoints: /status, /health/deep, /me."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from tools.gimo_server.models import StatusResponse
from tools.gimo_server.security import check_rate_limit
from tools.gimo_server.security.access_control import require_read_only_access
from tools.gimo_server.security.auth import AuthContext, SESSION_COOKIE_NAME, session_store
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.providers.service import ProviderService
from tools.gimo_server.version import __version__

router = APIRouter(tags=["core"])


@router.get("/status", response_model=StatusResponse)
def get_status(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    return {"version": __version__, "uptime_seconds": time.time() - request.app.state.start_time}


@router.get("/health/deep")
async def get_health_deep(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    import shutil
    uptime_seconds = time.time() - request.app.state.start_time
    ops_dir = OpsService.OPS_DIR
    try:
        disk_total_bytes, _disk_used_bytes, disk_free_bytes = shutil.disk_usage(ops_dir)
    except Exception:
        disk_free_bytes = None
        disk_total_bytes = None

    provider_ok = await ProviderService.health_check()
    return {
        "status": "ok" if provider_ok else "degraded",
        "version": __version__,
        "uptime_seconds": uptime_seconds,
        "checks": {
            "ops_dir_exists": ops_dir.exists(),
            "provider_health": provider_ok,
            "gics_attached": bool(getattr(request.app.state, "gics", None)),
            "run_worker_attached": bool(getattr(request.app.state, "run_worker", None)),
        },
        "storage": {
            "ops_dir": str(ops_dir),
            "disk_free_bytes": disk_free_bytes,
            "disk_total_bytes": disk_total_bytes,
        },
    }


@router.get("/me")
def get_me(request: Request):
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_value:
        raise HTTPException(status_code=401, detail="Session missing")
    session = session_store.validate(cookie_value)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")
    return {
        "email": session.email,
        "displayName": session.display_name,
        "plan": session.plan,
        "firebaseUser": bool(session.firebase_user),
        "role": session.role,
    }
