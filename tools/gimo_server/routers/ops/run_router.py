from __future__ import annotations
from typing import List, Optional, Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import (
    OpsApproved, OpsApproveResponse, OpsRun, OpsCreateRunRequest,
    WorkflowExecuteRequest, WorkflowGraph, WorkflowCheckpoint
)
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.storage_service import StorageService
from tools.gimo_server.services.graph_engine import GraphEngine
from tools.gimo_server.services.confidence_service import ConfidenceService
from tools.gimo_server.services.trust_engine import TrustEngine
from .common import _require_role, _actor_label, _WORKFLOW_ENGINES

router = APIRouter()

@router.post(
    "/drafts/{draft_id}/approve", 
    response_model=OpsApproveResponse,
    responses={404: {"description": "Draft not found"}}
)
async def approve_draft(
    request: Request,
    draft_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
    auto_run: Annotated[Optional[bool], Query(description="Override default_auto_run from config")] = None,
):
    _require_role(auth, "operator")
    actor = _actor_label(auth)
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    try:
        approved = OpsService.approve_draft(draft_id, approved_by=actor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/drafts/{draft_id}/approve", approved.id, operation="WRITE", actor=actor)

    should_run = auto_run if auto_run is not None else OpsService.get_config().default_auto_run
    run = None
    if should_run:
        try:
            run = OpsService.create_run(approved.id)
            audit_log("OPS", "/ops/runs", run.id, operation="WRITE_AUTO", actor=actor)
        except (PermissionError, ValueError):
            pass
    return OpsApproveResponse(approved=approved, run=run)

@router.get("/approved", response_model=List[OpsApproved])
async def list_approved(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    return OpsService.list_approved()

@router.get(
    "/approved/{approved_id}", 
    response_model=OpsApproved,
    responses={404: {"description": "Approved entry not found"}}
)
async def get_approved(
    request: Request,
    approved_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    approved = OpsService.get_approved(approved_id)
    if not approved:
        raise HTTPException(status_code=404, detail="Approved entry not found")
    return approved

@router.post(
    "/runs", 
    response_model=OpsRun, 
    status_code=201,
    responses={
        403: {"description": "Permission denied"},
        404: {"description": "Approved plan not found"}
    }
)
async def create_run(
    request: Request,
    body: OpsCreateRunRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    try:
        run = OpsService.create_run(body.approved_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", "/ops/runs", run.id, operation="WRITE", actor=_actor_label(auth))
    return run

@router.get("/runs", response_model=List[OpsRun])
async def list_runs(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    return OpsService.list_runs()

@router.get(
    "/runs/{run_id}", 
    response_model=OpsRun,
    responses={404: {"description": "Run not found"}}
)
async def get_run(
    request: Request,
    run_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    run = OpsService.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run

@router.post(
    "/runs/{run_id}/cancel", 
    response_model=OpsRun,
    responses={
        404: {"description": "Run not found"},
        409: {"description": "Run already in terminal state"}
    }
)
async def cancel_run(
    request: Request,
    run_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    actor = _actor_label(auth)
    run = OpsService.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("done", "error", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Run already in terminal state: {run.status}")
    try:
        OpsService.set_gics(getattr(request.app.state, "gics", None))
        run = OpsService.update_run_status(run_id, "cancelled", msg=f"Cancelled by {actor}")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/runs/{run_id}/cancel", run.id, operation="WRITE", actor=actor)
    return run

@router.post("/workflows/execute")
async def execute_workflow(
    request: Request,
    body: WorkflowExecuteRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    engine = GraphEngine(
        body.workflow,
        storage=storage,
        persist_checkpoints=bool(body.persist_checkpoints),
        workflow_timeout_seconds=body.workflow_timeout_seconds,
        confidence_service=ConfidenceService(TrustEngine(storage)),
    )
    _WORKFLOW_ENGINES[body.workflow.id] = engine
    state = await engine.execute(initial_state=body.initial_state)
    audit_log("OPS", "/ops/workflows/execute", body.workflow.id, operation="WRITE", actor=_actor_label(auth))
    return {
        "workflow_id": body.workflow.id,
        "checkpoint_count": len(state.checkpoints),
        "paused": bool(state.data.get("execution_paused", False)),
        "aborted_reason": state.data.get("aborted_reason"),
        "state": state.model_dump(),
    }

@router.get("/workflows/{workflow_id}/checkpoints")
async def list_workflow_checkpoints(
    request: Request,
    workflow_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    items = storage.list_checkpoints(workflow_id)
    audit_log("OPS", f"/ops/workflows/{workflow_id}/checkpoints", str(len(items)), operation="READ", actor=_actor_label(auth))
    return {"items": items, "count": len(items)}

@router.post(
    "/workflows/{workflow_id}/resume",
    responses={
        404: {"description": "Workflow not found"},
        409: {"description": "No checkpoints available"},
        400: {"description": "Resume failed"}
    }
)
async def resume_workflow(
    request: Request,
    workflow_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
    from_checkpoint: Annotated[int, Query(description="Checkpoint index to resume from (default: last)")] = -1,
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    engine = _WORKFLOW_ENGINES.get(workflow_id)
    if engine is None:
        persisted = storage.get_workflow(workflow_id)
        if not persisted or not isinstance(persisted.get("data"), dict):
            raise HTTPException(status_code=404, detail="Workflow not found")
        try:
            workflow = WorkflowGraph.model_validate(persisted["data"])
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Invalid persisted workflow: {exc}")
        engine = GraphEngine(
            workflow, 
            storage=storage, 
            persist_checkpoints=True,
            confidence_service=ConfidenceService(TrustEngine(storage)),
        )
        raw_checkpoints = storage.list_checkpoints(workflow_id)
        engine.state.checkpoints = [WorkflowCheckpoint.model_validate(item) for item in raw_checkpoints]
        if engine.state.checkpoints:
            engine.state.data = dict(engine.state.checkpoints[-1].state)
        _WORKFLOW_ENGINES[workflow_id] = engine
    if not engine.state.checkpoints:
        raise HTTPException(status_code=409, detail="No checkpoints available to resume")
    try:
        next_node = engine.resume_from_checkpoint(from_checkpoint)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    state = await engine.execute()
    audit_log("OPS", f"/ops/workflows/{workflow_id}/resume", f"checkpoint={from_checkpoint}", operation="WRITE", actor=_actor_label(auth))
    return {
        "workflow_id": workflow_id,
        "resumed_from_checkpoint": from_checkpoint,
        "next_node": next_node,
        "checkpoint_count": len(state.checkpoints),
        "state": state.model_dump(),
    }
