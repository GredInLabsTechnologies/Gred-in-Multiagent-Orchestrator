from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.observability_service import ObservabilityService
from tools.gimo_server.services.notification_service import NotificationService
from .common import _require_role, _actor_label

router = APIRouter()

@router.get("/observability/metrics")
async def observability_metrics(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = ObservabilityService.get_metrics()
    audit_log("OPS", "/ops/observability/metrics", "read", operation="READ", actor=_actor_label(auth))
    return data

@router.get("/observability/traces")
async def observability_traces(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
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
    _rl: Annotated[None, Depends(check_rate_limit)],
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
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    alerts = ObservabilityService.get_alerts()
    audit_log("OPS", "/ops/observability/alerts", str(len(alerts)), operation="READ", actor=_actor_label(auth))
    return {"items": alerts, "count": len(alerts)}


@router.get("/observability/rate-limits")
async def observability_rate_limits(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    from tools.gimo_server.security.rate_limit import rate_limit_store, ROLE_RATE_LIMITS, RATE_LIMIT_WINDOW_SECONDS
    from datetime import datetime

    now = datetime.now()
    entries = []
    for key, data in rate_limit_store.items():
        elapsed = (now - data["start_time"]).total_seconds()
        if elapsed > RATE_LIMIT_WINDOW_SECONDS:
            continue
        parts = key.split(":", 1)
        ip = parts[0]
        role = parts[1] if len(parts) > 1 else "unknown"
        limit = ROLE_RATE_LIMITS.get(role, 0)
        entries.append({
            "ip": ip,
            "role": role,
            "count": data["count"],
            "limit": limit,
            "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            "remaining": max(0, limit - data["count"]),
        })
    return {"entries": entries, "role_limits": ROLE_RATE_LIMITS}


@router.get("/observability/migration-status")
async def observability_migration_status(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    from tools.gimo_server.services.plan_migration_service import PlanMigrationService
    plans = PlanMigrationService.audit_migration_status()
    runs = PlanMigrationService.audit_run_routing_coverage()
    audit_log("OPS", "/ops/observability/migration-status", "read", operation="READ", actor=_actor_label(auth))
    return {"plans": plans, "runs": runs}


@router.get("/realtime/metrics")
async def realtime_metrics(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = NotificationService.get_metrics()
    audit_log("OPS", "/ops/realtime/metrics", "read", operation="READ", actor=_actor_label(auth))
    return data
