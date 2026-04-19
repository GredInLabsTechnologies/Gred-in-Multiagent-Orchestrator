from __future__ import annotations
import logging
from pathlib import Path
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from tools.gimo_server.security import (
    audit_log,
    check_rate_limit,
    get_active_repo_dir,
    get_allowed_paths,
    serialize_allowlist,
    verify_token,
)
from tools.gimo_server.security.access_control import require_read_only_access
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.observability_pkg.observability_service import ObservabilityService
from tools.gimo_server.services.notification_service import NotificationService
from .common import _require_role, _actor_label

logger = logging.getLogger("orchestrator.routers.ops.observability")

router = APIRouter()


@router.get("/audit/tail")
def get_audit_tail(
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    limit: Annotated[int, Query(ge=10, le=500)] = 200,
):
    """Tail the orchestrator audit log file (migrated from /ui/audit)."""
    return {"lines": FileService.tail_audit_lines(limit=limit)}


@router.get("/allowlist")
def get_allowlist(
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """List allowed paths within the active repo (migrated from /ui/allowlist)."""
    base_dir = get_active_repo_dir()
    allowed_paths = get_allowed_paths(base_dir)
    items = serialize_allowlist(allowed_paths)
    safe_items = []
    for item in items:
        try:
            resolved = Path(item["path"]).resolve()
            if not is_within(base_dir, resolved):
                logger.warning("Rejected allowlist path outside base %s: %s", base_dir, item.get("path"))
                continue
            item["path"] = str(resolved.relative_to(base_dir))
            safe_items.append(item)
        except (ValueError, TypeError, OSError) as exc:
            logger.warning("Failed to relativize allowlist path %s: %s", item.get("path"), exc)
            continue
    return {"paths": safe_items}

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
    from tools.gimo_server.security.rate_limit import (
        rate_limit_store,
        ROLE_RATE_LIMITS,
        RATE_LIMIT_WINDOW_SECONDS,
        window_elapsed_seconds,
    )
    from datetime import datetime

    now = datetime.now()
    entries = []
    for key, data in rate_limit_store.items():
        elapsed = window_elapsed_seconds(data, now)
        if elapsed is None or elapsed > RATE_LIMIT_WINDOW_SECONDS:
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
    # R18 Change 9 — always enumerate known roles so dashboards never see
    # an empty list on a quiet window; zero-count placeholders fill gaps.
    observed_roles = {e["role"] for e in entries}
    for role, limit in ROLE_RATE_LIMITS.items():
        if role not in observed_roles:
            entries.append({
                "ip": "(none)",
                "role": role,
                "count": 0,
                "limit": limit,
                "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
                "remaining": limit,
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


@router.get("/observability/duration-stats")
async def observability_duration_stats(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    operation: Annotated[str | None, Query()] = None,
):
    """
    Get duration statistics for operations (GAEP Phase 1).

    Query params:
        operation: Filter by operation type (e.g., "plan", "run", "merge")

    Returns aggregated statistics: total_samples, success_rate, avg_duration, p50, p95, max.
    """
    _require_role(auth, "operator")
    from tools.gimo_server.services.timeout.duration_telemetry_service import DurationTelemetryService
    from tools.gimo_server.services.ops import OpsService

    # Inject GICS
    DurationTelemetryService.set_gics(getattr(request.app.state, "gics", None))

    if operation:
        stats = DurationTelemetryService.get_stats_for_operation(operation)
        audit_log("OPS", f"/ops/observability/duration-stats?operation={operation}",
                 "read", operation="READ", actor=_actor_label(auth))
        return stats
    else:
        # Return stats for all known operations
        operations = ["plan", "run", "merge"]
        all_stats = {
            op: DurationTelemetryService.get_stats_for_operation(op)
            for op in operations
        }
        audit_log("OPS", "/ops/observability/duration-stats",
                 "read", operation="READ", actor=_actor_label(auth))
        return {"operations": all_stats}
