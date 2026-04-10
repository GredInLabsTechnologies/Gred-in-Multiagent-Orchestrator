"""
GIMO Mesh Router — Phase 1.

Device registry, heartbeat, enrollment, approval, and status endpoints.
All endpoints require operator role minimum.
"""

from __future__ import annotations

import logging
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from tools.gimo_server.models.mesh import (
    DeviceMode,
    HeartbeatPayload,
    MeshDeviceInfo,
    MeshStatus,
    ThermalEvent,
)
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.mesh.registry import MeshRegistry

from .common import _actor_label, _require_role

router = APIRouter(prefix="/ops/mesh", tags=["mesh"])
logger = logging.getLogger("orchestrator.routers.ops.mesh")


def _get_registry(request: Request) -> MeshRegistry:
    registry = getattr(request.app.state, "mesh_registry", None)
    if registry is None:
        raise HTTPException(503, detail="Mesh service not initialized")
    return registry


def _get_mesh_enabled(request: Request) -> bool:
    from tools.gimo_server.services.ops_service import OpsService
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    return OpsService.get_config().mesh_enabled


# ── Status ───────────────────────────────────────────────────

@router.get("/status")
async def mesh_status(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> MeshStatus:
    _require_role(auth, "operator")
    registry = _get_registry(request)
    return registry.get_status(_get_mesh_enabled(request))


# ── Device list ──────────────────────────────────────────────

@router.get("/devices")
async def list_devices(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> List[MeshDeviceInfo]:
    _require_role(auth, "operator")
    registry = _get_registry(request)
    return registry.list_devices()


# ── Single device ────────────────────────────────────────────

@router.get("/devices/{device_id}")
async def get_device(
    device_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> MeshDeviceInfo:
    _require_role(auth, "operator")
    registry = _get_registry(request)
    device = registry.get_device(device_id)
    if device is None:
        raise HTTPException(404, detail=f"Device {device_id} not found")
    return device


# ── Enrollment ───────────────────────────────────────────────

class EnrollRequest(BaseModel):
    device_id: str
    name: str = ""
    device_mode: DeviceMode = DeviceMode.inference
    device_class: str = "desktop"


@router.post("/enroll")
async def enroll_device(
    request: Request,
    body: EnrollRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> MeshDeviceInfo:
    _require_role(auth, "operator")
    if not _get_mesh_enabled(request):
        raise HTTPException(403, detail="Mesh is disabled")

    registry = _get_registry(request)
    existing = registry.get_device(body.device_id)
    if existing is not None:
        raise HTTPException(409, detail=f"Device {body.device_id} already enrolled")

    device = registry.enroll_device(
        device_id=body.device_id,
        name=body.name,
        device_mode=body.device_mode,
        device_class=body.device_class,
    )
    audit_log("OPS", "/ops/mesh/enroll", body.device_id, operation="WRITE", actor=_actor_label(auth))
    return device


# ── Approve / Refuse ─────────────────────────────────────────

@router.post("/devices/{device_id}/approve")
async def approve_device(
    device_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> MeshDeviceInfo:
    _require_role(auth, "admin")
    registry = _get_registry(request)
    try:
        device = registry.approve_device(device_id)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    audit_log("OPS", f"/ops/mesh/devices/{device_id}/approve", device_id, operation="WRITE", actor=_actor_label(auth))
    return device


@router.post("/devices/{device_id}/refuse")
async def refuse_device(
    device_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> MeshDeviceInfo:
    _require_role(auth, "admin")
    registry = _get_registry(request)
    try:
        device = registry.refuse_device(device_id)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    audit_log("OPS", f"/ops/mesh/devices/{device_id}/refuse", device_id, operation="WRITE", actor=_actor_label(auth))
    return device


# ── Remove device ────────────────────────────────────────────

@router.delete("/devices/{device_id}")
async def remove_device(
    device_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> dict:
    _require_role(auth, "admin")
    registry = _get_registry(request)
    removed = registry.remove_device(device_id)
    if not removed:
        raise HTTPException(404, detail=f"Device {device_id} not found")
    audit_log("OPS", f"/ops/mesh/devices/{device_id}", device_id, operation="DELETE", actor=_actor_label(auth))
    return {"removed": device_id}


# ── Heartbeat ────────────────────────────────────────────────

@router.post("/heartbeat")
async def heartbeat(
    request: Request,
    payload: HeartbeatPayload,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> MeshDeviceInfo:
    _require_role(auth, "operator")
    registry = _get_registry(request)
    try:
        device = registry.process_heartbeat(payload)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return device


# ── Thermal events ───────────────────────────────────────────

@router.post("/thermal-event")
async def report_thermal_event(
    request: Request,
    event: ThermalEvent,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> dict:
    _require_role(auth, "operator")
    registry = _get_registry(request)
    registry.record_thermal_event(event)

    # Feed telemetry service for profile + GICS integration
    from tools.gimo_server.services.mesh.telemetry import TelemetryService
    telemetry = TelemetryService()
    profile = telemetry.ingest_thermal_event(event)
    gics = getattr(request.app.state, "gics", None)
    telemetry.feed_gics(gics, event, profile)

    audit_log("OPS", "/ops/mesh/thermal-event", event.device_id, operation="WRITE", actor=_actor_label(auth))
    return {"recorded": True, "health_score": profile.health_score}


@router.get("/thermal-history")
async def thermal_history(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    device_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list:
    _require_role(auth, "operator")
    registry = _get_registry(request)
    return registry.get_thermal_history(device_id=device_id, limit=limit)


# ── Eligible devices ─────────────────────────────────────────

@router.get("/eligible")
async def eligible_devices(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> List[MeshDeviceInfo]:
    _require_role(auth, "operator")
    registry = _get_registry(request)
    return registry.get_eligible_devices(_get_mesh_enabled(request))


# ── Thermal profiles + health ────────────────────────────────

@router.get("/profiles")
async def list_thermal_profiles(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> list:
    _require_role(auth, "operator")
    from tools.gimo_server.services.mesh.telemetry import TelemetryService
    telemetry = TelemetryService()
    return [p.to_dict() for p in telemetry.list_profiles()]


@router.get("/profiles/{device_id}")
async def get_thermal_profile(
    device_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> dict:
    _require_role(auth, "operator")
    from tools.gimo_server.services.mesh.telemetry import TelemetryService
    telemetry = TelemetryService()
    return telemetry.get_profile(device_id).to_dict()


# ── Enrollment tokens ────────────────────────────────────────

def _get_enrollment(request: Request):
    from tools.gimo_server.services.mesh.enrollment import EnrollmentService
    registry = _get_registry(request)
    return EnrollmentService(registry)


class ClaimRequest(BaseModel):
    token: str
    device_id: str
    name: str = ""
    device_mode: DeviceMode = DeviceMode.inference
    device_class: str = "desktop"


@router.post("/enrollment/token")
async def create_enrollment_token(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    ttl_minutes: Annotated[int, Query(ge=1, le=1440)] = 15,
):
    _require_role(auth, "admin")
    if not _get_mesh_enabled(request):
        raise HTTPException(403, detail="Mesh is disabled")
    svc = _get_enrollment(request)
    token = svc.create_token(ttl_minutes=ttl_minutes)
    audit_log("OPS", "/ops/mesh/enrollment/token", "created", operation="WRITE", actor=_actor_label(auth))
    return {"token": token.token, "expires_at": token.expires_at.isoformat()}


@router.get("/enrollment/tokens")
async def list_enrollment_tokens(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    svc = _get_enrollment(request)
    return [t.model_dump(mode="json") for t in svc.list_tokens()]


@router.post("/enrollment/claim")
async def claim_enrollment(
    request: Request,
    body: ClaimRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> MeshDeviceInfo:
    _require_role(auth, "operator")
    if not _get_mesh_enabled(request):
        raise HTTPException(403, detail="Mesh is disabled")
    svc = _get_enrollment(request)
    try:
        device = svc.claim(
            token_str=body.token,
            device_id=body.device_id,
            name=body.name,
            device_mode=body.device_mode,
            device_class=body.device_class,
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    audit_log("OPS", "/ops/mesh/enrollment/claim", body.device_id, operation="WRITE", actor=_actor_label(auth))
    return device


@router.delete("/enrollment/token/{token_str}")
async def revoke_enrollment_token(
    token_str: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    svc = _get_enrollment(request)
    if not svc.revoke_token(token_str):
        raise HTTPException(404, detail="Token not found")
    audit_log("OPS", "/ops/mesh/enrollment/token", "revoked", operation="DELETE", actor=_actor_label(auth))
    return {"revoked": True}


# ── Audit log ────────────────────────────────────────────────

@router.get("/audit")
async def query_audit(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    category: Annotated[str | None, Query()] = None,
    device_id: Annotated[str | None, Query()] = None,
    task_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list:
    _require_role(auth, "admin")
    from tools.gimo_server.services.mesh.audit import MeshAuditService
    return MeshAuditService().query(
        category=category, device_id=device_id, task_id=task_id, limit=limit,
    )


@router.get("/audit/receipt/{receipt_id}")
async def correlate_receipt(
    receipt_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
) -> list:
    _require_role(auth, "admin")
    from tools.gimo_server.services.mesh.audit import MeshAuditService
    return MeshAuditService().correlate_receipt(receipt_id)
