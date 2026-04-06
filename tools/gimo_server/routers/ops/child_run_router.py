"""API router for child run management (wake-on-demand)."""
from __future__ import annotations
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Query
from ...models.core import ChildRunRequest
from ...services.child_run_service import ChildRunService
from ...services.ops_service import OpsService

router = APIRouter(prefix="/child-runs", tags=["child-runs"])


@router.get("", response_model=List[Dict[str, Any]])
async def list_child_runs(
    status: str = Query(default=None, description="Filter by status"),
):
    """List all child runs across all parents."""
    all_runs = OpsService.list_runs()
    children = [
        {
            "id": r.id,
            "status": r.status,
            "parent_run_id": r.parent_run_id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
        }
        for r in all_runs
        if getattr(r, "parent_run_id", None)
    ]
    if status:
        children = [c for c in children if c["status"] == status]
    return children


@router.post("/spawn", response_model=Dict[str, Any])
async def spawn_child(req: ChildRunRequest):
    try:
        child = ChildRunService.spawn_child(
            parent_run_id=req.parent_run_id, prompt=req.prompt,
            context=req.context, agent_profile_role=req.agent_profile,
        )
        return {"child_run_id": child.id, "status": child.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{parent_run_id}/pause")
async def pause_parent(parent_run_id: str):
    try:
        ChildRunService.pause_parent(parent_run_id)
        return {"status": "awaiting_subagents"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{parent_run_id}/children")
async def get_children(parent_run_id: str):
    return ChildRunService.get_children_status(parent_run_id)
