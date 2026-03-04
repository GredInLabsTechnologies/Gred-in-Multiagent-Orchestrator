from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.observability_service import ObservabilityService
from .common import _require_role, _actor_label

router = APIRouter()

@router.get("/observability/metrics")
async def observability_metrics(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = ObservabilityService.get_metrics()
    audit_log("OPS", "/ops/observability/metrics", "read", operation="READ", actor=_actor_label(auth))
    return data

@router.get("/observability/traces")
async def observability_traces(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
    limit: Annotated[int, Query(ge=1, le=500)] = 20,
):
    _require_role(auth, "operator")
    items = ObservabilityService.list_traces(limit=limit)
    audit_log("OPS", "/ops/observability/traces", str(limit), operation="READ", actor=_actor_label(auth))
    return {"items": items, "count": len(items)}

@router.get("/observability/traces/{trace_id}", responses={404: {"description": "Trace not found"}})
async def observability_trace_detail(
    trace_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    trace = ObservabilityService.get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    
    audit_log("OPS", f"/ops/observability/traces/{trace_id}", "read", operation="READ", actor=_actor_label(auth))
    return trace


@router.get("/observability/alerts")
async def observability_alerts(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    alerts = ObservabilityService.get_alerts()
    audit_log("OPS", "/ops/observability/alerts", str(len(alerts)), operation="READ", actor=_actor_label(auth))
    return {"items": alerts, "count": len(alerts)}
