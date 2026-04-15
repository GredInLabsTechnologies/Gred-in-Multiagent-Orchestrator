"""
Checkpoint Router — Phase 5 of SEA.

Endpoints for resuming operations from checkpoints.
"""

from __future__ import annotations
import logging
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.security.safe_log import sanitize_for_log
from tools.gimo_server.services.checkpoint_service import CheckpointService
from tools.gimo_server.services.ops_service import OpsService
from .common import _require_role, _actor_label

router = APIRouter()
logger = logging.getLogger("orchestrator.routers.ops.checkpoint")


@router.get("/checkpoints")
async def list_checkpoints(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    operation: Annotated[str | None, Query()] = None,
    operation_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    """
    Lista checkpoints resumables disponibles.

    Query params:
        operation: Filter by operation type (e.g., "plan", "run")
        operation_id: Filter by operation ID
        limit: Maximum checkpoints to return (default 50, max 100)

    Returns:
        List of checkpoint metadata
    """
    _require_role(auth, "operator")

    # Inject GICS
    CheckpointService.set_gics(getattr(request.app.state, "gics", None))

    checkpoints = CheckpointService.list_resumable(
        operation=operation,
        operation_id=operation_id,
        limit=limit
    )

    audit_log(
        "OPS",
        f"/ops/checkpoints?operation={operation or 'all'}",
        str(len(checkpoints)),
        operation="READ",
        actor=_actor_label(auth)
    )

    return {
        "checkpoints": checkpoints,
        "count": len(checkpoints),
    }


@router.get("/checkpoints/stats")
async def get_checkpoint_stats(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """
    Obtiene estadísticas de checkpoints.

    Returns:
        Statistics about checkpoints (total, resumable, expired, by_operation)
    """
    _require_role(auth, "operator")

    # Inject GICS
    CheckpointService.set_gics(getattr(request.app.state, "gics", None))

    stats = CheckpointService.get_stats()

    audit_log(
        "OPS",
        "/ops/checkpoints/stats",
        "read",
        operation="READ",
        actor=_actor_label(auth)
    )

    return stats


@router.get("/checkpoints/{checkpoint_id}")
async def get_checkpoint(
    checkpoint_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """
    Obtiene detalles de un checkpoint específico.

    Returns:
        Checkpoint data including state
    """
    _require_role(auth, "operator")

    # Inject GICS
    CheckpointService.set_gics(getattr(request.app.state, "gics", None))

    checkpoint = CheckpointService.get_checkpoint(checkpoint_id)

    if not checkpoint:
        raise HTTPException(
            status_code=404,
            detail=f"Checkpoint not found: {checkpoint_id}"
        )

    audit_log(
        "OPS",
        f"/ops/checkpoints/{checkpoint_id}",
        "read",
        operation="READ",
        actor=_actor_label(auth)
    )

    return checkpoint


@router.post("/checkpoints/{checkpoint_id}/resume")
async def resume_from_checkpoint(
    checkpoint_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """
    Reanuda operación desde checkpoint.

    Path params:
        checkpoint_id: Checkpoint identifier

    Returns:
        Result of resumed operation
    """
    _require_role(auth, "operator")

    # Inject GICS
    CheckpointService.set_gics(getattr(request.app.state, "gics", None))
    OpsService.set_gics(getattr(request.app.state, "gics", None))

    # Retrieve checkpoint
    checkpoint = CheckpointService.get_checkpoint(checkpoint_id)

    if not checkpoint:
        raise HTTPException(
            status_code=404,
            detail=f"Checkpoint not found: {checkpoint_id}"
        )

    if not checkpoint.get("resumable", False):
        raise HTTPException(
            status_code=400,
            detail=f"Checkpoint is not resumable: {checkpoint_id}"
        )

    operation = checkpoint.get("operation")
    operation_id = checkpoint.get("operation_id")
    state = checkpoint.get("state", {})

    logger.info(
        "Resuming %s operation %s from checkpoint %s",
        sanitize_for_log(operation),
        sanitize_for_log(operation_id),
        sanitize_for_log(checkpoint_id),
    )

    # Resume based on operation type
    if operation == "plan":
        result = await _resume_plan_generation(
            checkpoint_id=checkpoint_id,
            operation_id=operation_id,
            state=state,
            request=request,
            auth=auth
        )
    elif operation == "run":
        result = await _resume_run_execution(
            checkpoint_id=checkpoint_id,
            operation_id=operation_id,
            state=state,
            request=request,
            auth=auth
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resume operation type: {operation}"
        )

    # Mark checkpoint as non-resumable (completed)
    CheckpointService.mark_non_resumable(checkpoint_id)

    audit_log(
        "OPS",
        f"/ops/checkpoints/{checkpoint_id}/resume",
        operation_id,
        operation="WRITE",
        actor=_actor_label(auth)
    )

    return result


async def _resume_plan_generation(
    checkpoint_id: str,
    operation_id: str,
    state: dict,
    request: Request,
    auth: AuthContext
) -> dict:
    """Resume plan generation from checkpoint state."""
    # Extract state
    stage = state.get("stage")
    completed_tasks = state.get("completed_tasks", [])
    state.get("partial_result", {})

    logger.info(
        "Resuming plan generation: stage=%s, completed_tasks=%d",
        sanitize_for_log(stage),
        len(completed_tasks),
    )

    raise HTTPException(
        status_code=501,
        detail="Plan resume is not yet implemented. Checkpoint was saved but cannot be resumed automatically.",
    )


async def _resume_run_execution(
    checkpoint_id: str,
    operation_id: str,
    state: dict,
    request: Request,
    auth: AuthContext
) -> dict:
    """Resume run execution from checkpoint state."""
    stage = state.get("stage")

    logger.info("Resuming run execution: stage=%s", sanitize_for_log(stage))

    raise HTTPException(
        status_code=501,
        detail="Run resume is not yet implemented. Checkpoint was saved but cannot be resumed automatically.",
    )


@router.delete("/checkpoints/{checkpoint_id}")
async def delete_checkpoint(
    checkpoint_id: str,
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """
    Elimina checkpoint.

    Path params:
        checkpoint_id: Checkpoint identifier

    Returns:
        Success confirmation
    """
    _require_role(auth, "operator")

    # Inject GICS
    CheckpointService.set_gics(getattr(request.app.state, "gics", None))

    deleted = CheckpointService.delete_checkpoint(checkpoint_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Checkpoint not found: {checkpoint_id}"
        )

    audit_log(
        "OPS",
        f"/ops/checkpoints/{checkpoint_id}",
        "deleted",
        operation="DELETE",
        actor=_actor_label(auth)
    )

    return {
        "deleted": True,
        "checkpoint_id": checkpoint_id,
    }
