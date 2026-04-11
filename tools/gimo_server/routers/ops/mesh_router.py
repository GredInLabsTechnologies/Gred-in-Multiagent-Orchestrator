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
    TaskResult,
    TaskStatus,
    ThermalEvent,
    UtilityTaskType,
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
    # Validate device_id format (prevent _safe_id failures downstream)
    import re
    if not body.device_id or not re.fullmatch(r"[a-zA-Z0-9._-]+", body.device_id) or body.device_id.startswith("."):
        raise HTTPException(400, detail=f"Invalid device_id format: {body.device_id!r}")
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


# ── Utility Task Queue ──────────────────────────────────────


def _get_task_queue(request: Request):
    from tools.gimo_server.services.mesh.task_queue import TaskQueue
    tq = getattr(request.app.state, "mesh_task_queue", None)
    if tq is None:
        registry = _get_registry(request)
        tq = TaskQueue(registry)
        request.app.state.mesh_task_queue = tq
    return tq


class CreateTaskRequest(BaseModel):
    task_type: UtilityTaskType
    payload: dict = {}
    timeout_seconds: int = 60
    min_ram_mb: int = 0
    min_api_level: int = 0
    requires_arch: str = ""
    workspace_id: str = "default"


@router.post("/tasks")
async def create_task(
    body: CreateTaskRequest,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    ws_svc = _get_workspace_service(request)
    # Validate workspace exists
    if body.workspace_id != "default":
        if ws_svc.get_workspace(body.workspace_id) is None:
            raise HTTPException(404, detail=f"Workspace {body.workspace_id} not found")
    # INV-L1: reject if workspace is not bound to current license
    _require_licensed_workspace(ws_svc, body.workspace_id)
    # INV-W6: reject task creation if workspace has no active Core
    registry = _get_registry(request)
    if not ws_svc.has_active_core(body.workspace_id, registry):
        raise HTTPException(409, detail=f"Workspace {body.workspace_id} has no active Core device — task dispatch blocked (INV-W6)")
    tq = _get_task_queue(request)
    task = tq.create_task(
        task_type=body.task_type,
        payload=body.payload,
        timeout_seconds=body.timeout_seconds,
        min_ram_mb=body.min_ram_mb,
        min_api_level=body.min_api_level,
        requires_arch=body.requires_arch,
        workspace_id=body.workspace_id,
    )
    return task.model_dump(mode="json")


@router.get("/tasks")
async def list_tasks(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    status: Annotated[str | None, Query()] = None,
    workspace_id: Annotated[str | None, Query()] = None,
):
    _require_role(auth, "operator")
    tq = _get_task_queue(request)
    filter_status = TaskStatus(status) if status else None
    tasks = tq.list_tasks(status=filter_status)
    # INV-W1: filter by workspace if specified
    if workspace_id:
        tasks = [t for t in tasks if t.workspace_id == workspace_id]
    return [t.model_dump(mode="json") for t in tasks]


@router.get("/tasks/poll/{device_id}")
async def poll_tasks(
    device_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Device polls for assigned tasks. Also triggers expiry and auto-assign."""
    _require_role(auth, "operator")
    registry = _get_registry(request)
    device = registry.get_device(device_id)
    if device is None:
        raise HTTPException(404, detail=f"Device {device_id} not found")
    mesh_enabled = _get_mesh_enabled(request)
    tq = _get_task_queue(request)
    tq.expire_stale()
    tq.auto_assign_pending(mesh_enabled)

    # INV-W6: no Core in workspace → no tasks dispatched
    ws_svc = _get_workspace_service(request)
    if not ws_svc.has_active_core(device.active_workspace_id, registry):
        return []

    tasks = tq.get_assigned_for_device(device_id, workspace_id=device.active_workspace_id)
    return [t.model_dump(mode="json") for t in tasks]


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    tq = _get_task_queue(request)
    task = tq.get_task(task_id)
    if not task:
        raise HTTPException(404, detail="Task not found")
    return task.model_dump(mode="json")


@router.post("/tasks/{task_id}/result")
async def submit_task_result(
    task_id: str,
    body: TaskResult,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    tq = _get_task_queue(request)
    if body.task_id != task_id:
        raise HTTPException(400, detail="task_id mismatch")
    # INV-W1: verify device is assigned to this task and in the right workspace
    existing = tq.get_task(task_id)
    if not existing:
        raise HTTPException(404, detail="Task not found")
    if existing.assigned_device_id and existing.assigned_device_id != body.device_id:
        raise HTTPException(403, detail="Task not assigned to this device")
    task = tq.complete_task(body)
    if not task:
        raise HTTPException(404, detail="Task not found")
    return task.model_dump(mode="json")


@router.delete("/tasks/{task_id}")
async def cancel_task(
    task_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    tq = _get_task_queue(request)
    if not tq.delete_task(task_id):
        raise HTTPException(404, detail="Task not found")
    return {"deleted": task_id}


# ═══════════════════════════════════════════════════════════════
# Workspaces — device session groups (INV-W1 to INV-W5)
# ═══════════════════════════════════════════════════════════════

def _get_workspace_service(request: Request):
    from tools.gimo_server.services.mesh.workspace_service import WorkspaceService
    svc = getattr(request.app.state, "workspace_service", None)
    if svc is None:
        svc = WorkspaceService()
        request.app.state.workspace_service = svc
    return svc


def _require_licensed_workspace(svc, workspace_id: str) -> None:
    """INV-L1: block operations on workspaces not bound to current license."""
    if not svc.is_workspace_licensed(workspace_id):
        raise HTTPException(
            403,
            detail=f"Workspace {workspace_id} is bound to a different license — blocked (INV-L1)",
        )


class CreateWorkspaceRequest(BaseModel):
    name: str
    owner_device_id: str = ""


class JoinWorkspaceRequest(BaseModel):
    code: str
    device_id: str
    device_mode: DeviceMode = DeviceMode.inference


class ActivateWorkspaceRequest(BaseModel):
    device_id: str
    workspace_id: str


@router.post("/workspaces")
async def create_workspace(
    body: CreateWorkspaceRequest,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    svc = _get_workspace_service(request)
    # Validate owner device exists if specified
    if body.owner_device_id:
        registry = _get_registry(request)
        if registry.get_device(body.owner_device_id) is None:
            raise HTTPException(404, detail=f"Owner device {body.owner_device_id} not found")
    ws = svc.create_workspace(name=body.name, owner_device_id=body.owner_device_id)
    audit_log("OPS", "/ops/mesh/workspaces", f"created workspace={ws.workspace_id} name={ws.name}", operation="WRITE", actor=_actor_label(auth))
    return ws.model_dump(mode="json")


@router.get("/workspaces")
async def list_workspaces(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    svc = _get_workspace_service(request)
    return [ws.model_dump(mode="json") for ws in svc.list_workspaces()]


@router.get("/workspaces/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    svc = _get_workspace_service(request)
    ws = svc.get_workspace(workspace_id)
    if ws is None:
        raise HTTPException(404, detail="Workspace not found")
    registry = _get_registry(request)
    members = svc.list_members(workspace_id)
    return {
        **ws.model_dump(mode="json"),
        "members": [m.model_dump(mode="json") for m in members],
        "licensed": svc.is_workspace_licensed(workspace_id),
        "core_active": svc.has_active_core(workspace_id, registry),
    }


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    svc = _get_workspace_service(request)
    registry = _get_registry(request)
    if not svc.delete_workspace(workspace_id, registry=registry):
        raise HTTPException(400, detail="Cannot delete workspace (default or not found)")
    audit_log("OPS", f"/ops/mesh/workspaces/{workspace_id}", workspace_id, operation="DELETE", actor=_actor_label(auth))
    return {"deleted": workspace_id}


# ── Pairing ─────────────────────────────────────────────────

@router.post("/workspaces/{workspace_id}/pair")
async def generate_pairing_code(
    workspace_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Generate 6-digit pairing code (INV-S3: 5 min TTL, single-use)."""
    _require_role(auth, "operator")
    svc = _get_workspace_service(request)
    _require_licensed_workspace(svc, workspace_id)
    pc = svc.generate_pairing_code(workspace_id)
    if pc is None:
        raise HTTPException(404, detail="Workspace not found")
    audit_log("OPS", f"/ops/mesh/workspaces/{workspace_id}/pair", workspace_id, operation="WRITE", actor=_actor_label(auth))
    return {"code": pc.code, "workspace_id": workspace_id, "expires_at": pc.expires_at.isoformat()}


@router.post("/workspaces/join")
async def join_workspace(
    body: JoinWorkspaceRequest,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Join workspace via pairing code (INV-S2: no invitation, no workspace)."""
    _require_role(auth, "operator")
    svc = _get_workspace_service(request)
    membership = svc.join_with_code(
        code=body.code,
        device_id=body.device_id,
        device_mode=body.device_mode,
    )
    if membership is None:
        raise HTTPException(403, detail="Invalid, expired, or already used pairing code")
    audit_log("OPS", "/ops/mesh/workspaces/join", f"device={body.device_id} workspace={membership.workspace_id}", operation="WRITE", actor=_actor_label(auth))
    return membership.model_dump(mode="json")


# ── Members ─────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/members")
async def list_workspace_members(
    workspace_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    svc = _get_workspace_service(request)
    if svc.get_workspace(workspace_id) is None:
        raise HTTPException(404, detail="Workspace not found")
    return [m.model_dump(mode="json") for m in svc.list_members(workspace_id)]


@router.delete("/workspaces/{workspace_id}/members/{device_id}")
async def remove_workspace_member(
    workspace_id: str,
    device_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Remove member (INV-W5: last owner cannot be removed)."""
    _require_role(auth, "admin")
    svc = _get_workspace_service(request)
    if not svc.remove_member(workspace_id, device_id):
        raise HTTPException(400, detail="Cannot remove (last owner or not found)")
    audit_log("OPS", f"/ops/mesh/workspaces/{workspace_id}/members/{device_id}", device_id, operation="DELETE", actor=_actor_label(auth))
    return {"removed": device_id, "workspace_id": workspace_id}


# ── Activate workspace ──────────────────────────────────────

@router.post("/workspaces/activate")
async def activate_workspace(
    body: ActivateWorkspaceRequest,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Switch active workspace for a device (INV-W2: exactly 1 active)."""
    _require_role(auth, "operator")
    svc = _get_workspace_service(request)
    registry = _get_registry(request)
    _require_licensed_workspace(svc, body.workspace_id)

    # Verify workspace exists
    ws = svc.get_workspace(body.workspace_id)
    if ws is None:
        raise HTTPException(404, detail="Workspace not found")

    # Verify device exists
    device = registry.get_device(body.device_id)
    if device is None:
        raise HTTPException(404, detail="Device not found")

    # Verify membership
    member = svc.get_member(body.workspace_id, body.device_id)
    if member is None:
        raise HTTPException(403, detail="Device not a member of this workspace")

    # INV-W2: cancel in-flight tasks on workspace switch
    if device.active_task_id:
        tq = _get_task_queue(request)
        orphaned = tq.get_task(device.active_task_id)
        if orphaned and orphaned.status in (TaskStatus.assigned, TaskStatus.running):
            from tools.gimo_server.models.mesh import TaskResult as _TR
            tq.complete_task(_TR(
                task_id=orphaned.task_id,
                device_id=device.device_id,
                status="failed",
                error="workspace switched — task cancelled",
                duration_ms=0,
            ))

    # INV-W3: load per-workspace mode
    device.active_workspace_id = body.workspace_id
    device.device_mode = member.device_mode
    device.active_task_id = ""
    registry.save_device(device)

    # INV-W6: check if workspace has an active Core
    core_active = svc.has_active_core(body.workspace_id, registry)

    audit_log("OPS", "/ops/mesh/workspaces/activate", f"device={body.device_id} workspace={body.workspace_id} mode={member.device_mode.value} core_active={core_active}", operation="WRITE", actor=_actor_label(auth))
    return {
        "device_id": body.device_id,
        "workspace_id": body.workspace_id,
        "device_mode": member.device_mode.value,
        "core_active": core_active,
    }


@router.get("/workspaces/device/{device_id}")
async def get_device_workspaces(
    device_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """List all workspaces a device belongs to."""
    _require_role(auth, "operator")
    svc = _get_workspace_service(request)
    return [m.model_dump(mode="json") for m in svc.get_device_workspaces(device_id)]


# ═══════════════════════════════════════════════════════════════
# Onboarding — zero-ADB device enrollment via 6-digit codes
# ═══════════════════════════════════════════════════════════════

def _get_onboarding_service(request: Request):
    from tools.gimo_server.services.mesh.onboarding import OnboardingService
    svc = getattr(request.app.state, "onboarding_service", None)
    if svc is None:
        svc = OnboardingService()
        request.app.state.onboarding_service = svc
    return svc


class OnboardCodeRequest(BaseModel):
    workspace_id: str = "default"


class RedeemCodeRequest(BaseModel):
    code: str
    device_id: str
    name: str = ""
    device_mode: DeviceMode = DeviceMode.inference
    device_class: str = "smartphone"


@router.post("/onboard/code")
async def generate_onboard_code(
    body: OnboardCodeRequest,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Admin generates a 6-digit onboarding code for a new device."""
    _require_role(auth, "admin")
    if not _get_mesh_enabled(request):
        raise HTTPException(403, detail="Mesh is disabled")

    # Validate workspace exists
    if body.workspace_id != "default":
        ws_svc = _get_workspace_service(request)
        if ws_svc.get_workspace(body.workspace_id) is None:
            raise HTTPException(404, detail=f"Workspace {body.workspace_id} not found")

    svc = _get_onboarding_service(request)
    oc = svc.create_code(workspace_id=body.workspace_id)
    audit_log("OPS", "/ops/mesh/onboard/code", f"workspace={body.workspace_id}", operation="WRITE", actor=_actor_label(auth))
    return {"code": oc.code, "workspace_id": oc.workspace_id, "expires_at": oc.expires_at.isoformat()}


@router.post("/onboard/redeem")
async def redeem_onboard_code(
    body: RedeemCodeRequest,
    request: Request,
):
    """Device redeems onboarding code — NO auth required.

    The code IS the authentication. Rate-limited to 5/min per IP.
    Returns bearer_token for all future requests.
    """
    # Manual rate-limit (no verify_token dependency)
    from tools.gimo_server.security.rate_limit import rate_limit_store
    from datetime import datetime as _dt, timezone as _tz
    client_ip = request.client.host if request.client else "unknown"
    rl_key = f"onboard:{client_ip}"
    now = _dt.now(_tz.utc)
    data = rate_limit_store.get(rl_key)
    if data is None:
        rate_limit_store[rl_key] = {"count": 1, "start_time": now}
    else:
        if (now - data["start_time"]).total_seconds() > 60:
            rate_limit_store[rl_key] = {"count": 1, "start_time": now}
        else:
            data["count"] += 1
            if data["count"] > 5:
                raise HTTPException(429, detail="Too many onboarding attempts. Try again in 1 minute.")

    # Validate device_id format
    import re
    if not body.device_id or not re.fullmatch(r"[a-zA-Z0-9._-]+", body.device_id) or body.device_id.startswith("."):
        raise HTTPException(400, detail=f"Invalid device_id format: {body.device_id!r}")

    svc = _get_onboarding_service(request)
    result = svc.redeem_code(
        code=body.code,
        device_id=body.device_id,
        name=body.name,
        device_mode=body.device_mode,
        device_class=body.device_class,
    )
    if result is None:
        raise HTTPException(403, detail="Invalid, expired, or already used onboarding code")

    audit_log("OPS", "/ops/mesh/onboard/redeem", f"device={body.device_id} workspace={result.workspace_id}", operation="WRITE", actor=f"onboard:{body.device_id}")
    return result.model_dump(mode="json")


@router.get("/onboard/discover")
async def discover_core(request: Request):
    """Unauthenticated endpoint for device discovery on LAN.

    Returns minimal Core info so a device can verify it found a real Core.
    """
    mesh_enabled = _get_mesh_enabled(request)
    return {
        "core_id": "gimo",
        "version": "1.0.0",
        "mesh_enabled": mesh_enabled,
    }


# ═══════════════════════════════════════════════════════════════
# Model Catalog — GGUF models for mesh devices
# ═══════════════════════════════════════════════════════════════

def _get_model_catalog(request: Request):
    from tools.gimo_server.services.mesh.model_catalog import ModelCatalogService
    svc = getattr(request.app.state, "model_catalog", None)
    if svc is None:
        svc = ModelCatalogService()
        request.app.state.model_catalog = svc
    return svc


@router.get("/models")
async def list_models(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """List available GGUF models for download."""
    _require_role(auth, "operator")
    catalog = _get_model_catalog(request)
    return [m.model_dump(mode="json") for m in catalog.list_models()]


@router.get("/models/{model_id}")
async def get_model_info(
    model_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Get metadata for a specific model."""
    _require_role(auth, "operator")
    catalog = _get_model_catalog(request)
    model = catalog.get_model(model_id)
    if model is None:
        raise HTTPException(404, detail=f"Model {model_id} not found")
    return model.model_dump(mode="json")


@router.get("/models/{model_id}/download")
async def download_model(
    model_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Stream a GGUF model file. Supports Range header for resume."""
    _require_role(auth, "operator")
    catalog = _get_model_catalog(request)
    path = catalog.get_model_path(model_id)
    if path is None:
        raise HTTPException(404, detail=f"Model {model_id} not found")

    from fastapi.responses import FileResponse
    file_size = path.stat().st_size

    # Support Range header for download resume
    range_header = request.headers.get("range")
    if range_header:
        from starlette.responses import StreamingResponse

        match = __import__("re").match(r"bytes=(\d+)-(\d*)", range_header)
        if not match:
            raise HTTPException(416, detail="Invalid Range header")

        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else file_size - 1
        if start >= file_size:
            raise HTTPException(416, detail="Range not satisfiable")

        def iter_range():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iter_range(),
            status_code=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(end - start + 1),
                "Accept-Ranges": "bytes",
                "Content-Type": "application/octet-stream",
                "Content-Disposition": f'attachment; filename="{path.name}"',
            },
        )

    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        filename=path.name,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        },
    )
