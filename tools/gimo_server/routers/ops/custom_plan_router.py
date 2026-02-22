from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, HTTPException

from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.custom_plan_service import (
    CustomPlan,
    CreatePlanRequest,
    UpdatePlanRequest,
    CustomPlanService,
)
from .common import _actor_label, _require_role

router = APIRouter()

_NOT_FOUND = "Plan not found"


@router.get("/custom-plans", response_model=List[CustomPlan])
async def list_plans(
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    """List all custom execution plans."""
    return CustomPlanService.list_plans()


@router.get("/custom-plans/{plan_id}", response_model=CustomPlan)
async def get_plan(
    plan_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    plan = CustomPlanService.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return plan


@router.post("/custom-plans", response_model=CustomPlan, status_code=201)
async def create_plan(
    body: CreatePlanRequest,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "operator")
    plan = CustomPlanService.create_plan(body)
    audit_log("PLANS", "/ops/custom-plans", plan.id, operation="CREATE", actor=_actor_label(auth))
    return plan


@router.put("/custom-plans/{plan_id}", response_model=CustomPlan)
async def update_plan(
    plan_id: str,
    body: UpdatePlanRequest,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "operator")
    plan = CustomPlanService.update_plan(plan_id, body)
    if not plan:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    audit_log("PLANS", f"/ops/custom-plans/{plan_id}", plan.id, operation="UPDATE", actor=_actor_label(auth))
    return plan


@router.delete("/custom-plans/{plan_id}", status_code=204)
async def delete_plan(
    plan_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "admin")
    if not CustomPlanService.delete_plan(plan_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    audit_log("PLANS", f"/ops/custom-plans/{plan_id}", plan_id, operation="DELETE", actor=_actor_label(auth))


@router.post("/custom-plans/{plan_id}/execute", response_model=CustomPlan)
async def execute_plan(
    plan_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    """Execute a custom plan — runs nodes layer-by-layer respecting the dependency graph."""
    _require_role(auth, "operator")
    plan = CustomPlanService.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    
    # Run in background to avoid HTTP timeout
    asyncio.create_task(CustomPlanService.execute_plan(plan_id))
    
    audit_log("PLANS", f"/ops/custom-plans/{plan_id}/execute", plan_id, operation="EXECUTE", actor=_actor_label(auth))
    return plan
