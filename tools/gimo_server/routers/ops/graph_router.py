"""OPS graph endpoint — migrated from legacy /ui/graph."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...security import check_rate_limit
from ...security.auth import AuthContext
from ...services.ops_service import OpsService
from ...services.plan_graph_builder import build_graph_from_ops_plan
from ...services.run_lifecycle import is_active_run_status
from ..ops.common import require_read, _WORKFLOW_ENGINES

router = APIRouter(prefix="/ops/graph", tags=["graph"])


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
    active_runs = [r for r in runs if is_active_run_status(getattr(r, "status", ""))]
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
