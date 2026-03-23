"""OPS graph endpoint — migrated from legacy /ui/graph."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...security import check_rate_limit
from ...security.auth import AuthContext
from ...services.ops_service import OpsService
from ...services.plan_graph_builder import build_graph_from_ops_plan
from ..ops.common import require_read, require_operator, _WORKFLOW_ENGINES

router = APIRouter(prefix="/ops/graph", tags=["graph"])


class TimeTravelRequest(BaseModel):
    action: str  # "replay" | "fork"
    checkpoint_index: int = -1
    state_patch: Optional[Dict[str, Any]] = None


def _get_graph_for_custom_plan():
    try:
        from ...services.custom_plan_service import CustomPlanService
        plans = CustomPlanService.list_plans()
        active = next((p for p in plans if p.get("status") == "active"), None)
        if active:
            return build_graph_from_ops_plan(active)
    except Exception:
        pass
    return None


def _get_graph_for_active_runs():
    runs = OpsService.list_runs()
    active_runs = [r for r in runs if r.status in ("pending", "running", "awaiting_subagents", "awaiting_review")]
    if active_runs:
        return build_graph_from_ops_plan(active_runs[0])
    return None


def _get_graph_for_pending_drafts():
    drafts = OpsService.list_drafts()
    pending = [d for d in drafts if d.status == "pending"]
    if pending:
        return build_graph_from_ops_plan(pending[0])
    return None


def _get_graph_for_recent_done_runs():
    runs = OpsService.list_runs()
    done = [r for r in runs if r.status in ("done", "error")]
    if done:
        return build_graph_from_ops_plan(done[0])
    return None


def _get_graph_for_approved_drafts():
    approved = OpsService.list_approved()
    if approved:
        return build_graph_from_ops_plan(approved[0])
    return None


def _build_engine_graph(engine):
    try:
        return engine.to_graph_dict()
    except Exception:
        return {"nodes": [], "edges": []}


@router.get("")
def get_graph(
    auth: AuthContext = Depends(require_read),
    _rl: None = Depends(check_rate_limit),
):
    """Generate dynamic graph structure for the UI based on active engines."""
    engine = None
    if _WORKFLOW_ENGINES:
        engine = list(_WORKFLOW_ENGINES.values())[-1]

    if not engine:
        result = _get_graph_for_custom_plan()
        if result:
            return result

        result = _get_graph_for_active_runs()
        if result:
            return result

        result = _get_graph_for_pending_drafts()
        if result:
            return result

        result = _get_graph_for_recent_done_runs()
        if result:
            return result

        result = _get_graph_for_approved_drafts()
        if result:
            return result

        return {"nodes": [], "edges": []}

    return _build_engine_graph(engine)


@router.post("/{workflow_id}/time-travel")
async def time_travel(
    workflow_id: str,
    request: TimeTravelRequest,
    auth: AuthContext = Depends(require_operator),
    _rl: None = Depends(check_rate_limit),
):
    """Fase 5: Time-Travel — replay o fork desde un checkpoint.

    - action=replay: re-ejecuta el engine desde el checkpoint indicado (in-place)
    - action=fork: crea un nuevo engine con estado editado, retorna fork_workflow_id
    """
    engine = _WORKFLOW_ENGINES.get(workflow_id)
    if not engine:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found or not active")

    if request.action == "replay":
        try:
            engine.replay_from_checkpoint(request.checkpoint_index)
        except (ValueError, IndexError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {
            "action": "replay",
            "workflow_id": workflow_id,
            "checkpoint_index": request.checkpoint_index,
            "timeline": engine.get_checkpoint_timeline(),
        }

    if request.action == "fork":
        try:
            fork_engine = engine.fork_from_checkpoint(
                request.checkpoint_index,
                request.state_patch,
            )
        except (ValueError, IndexError) as e:
            raise HTTPException(status_code=400, detail=str(e))

        fork_id = fork_engine.state.data.get("fork_id", f"fork_{workflow_id}")
        _WORKFLOW_ENGINES[fork_id] = fork_engine
        return {
            "action": "fork",
            "workflow_id": workflow_id,
            "fork_workflow_id": fork_id,
            "checkpoint_index": request.checkpoint_index,
            "timeline": fork_engine.get_checkpoint_timeline(),
        }

    raise HTTPException(status_code=400, detail=f"action inválida: '{request.action}'. Use 'replay' o 'fork'")


class WorkflowStreamRequest(BaseModel):
    initial_state: Dict[str, Any] = {}
    persist_checkpoints: bool = False
    workflow_timeout_seconds: Optional[int] = None


@router.post("/workflows/{workflow_id}/execute/stream")
async def execute_workflow_stream(
    workflow_id: str,
    request: WorkflowStreamRequest,
    auth: AuthContext = Depends(require_operator),
    _rl: None = Depends(check_rate_limit),
):
    """Fase 7: Streaming SSE de la ejecución del grafo.

    Emite eventos SSE: workflow_start, node_start, node_end, state_update,
    checkpoint, command, send_map, send_reduce, cycle_iteration, pause, error, done.
    """
    engine = _WORKFLOW_ENGINES.get(workflow_id)
    if not engine:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found or not active")

    async def _event_generator():
        async for event in engine.execute_stream(request.initial_state or None):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
