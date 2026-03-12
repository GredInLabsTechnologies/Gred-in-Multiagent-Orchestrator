from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import PolicyConfig
from tools.gimo_server.services.policy_service import PolicyService
from .common import _require_role, _actor_label

router = APIRouter()


@router.get("/policy", response_model=PolicyConfig)
async def get_policy_config(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    cfg = PolicyService.get_config()
    audit_log("OPS", "/ops/policy", "read", operation="READ", actor=_actor_label(auth))
    return cfg


@router.put("/policy", response_model=PolicyConfig)
async def set_policy_config(
    request: Request,
    body: PolicyConfig,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    cfg = PolicyService.set_config(body)
    audit_log("OPS", "/ops/policy", "updated", operation="WRITE", actor=_actor_label(auth))
    return cfg


@router.post("/policy/decide", responses={400: {"description": "Bad Request"}})
async def policy_decide(
    request: Request,
    body: dict,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    tool = str(body.get("tool", "")).strip()
    context = str(body.get("context", "*")).strip() or "*"
    if not tool:
        raise HTTPException(status_code=400, detail="tool is required")
    try:
        trust_score = float(body.get("trust_score", 0.0) or 0.0)
        confidence_score = float(body.get("confidence_score", 1.0) or 1.0)
    except Exception:
        raise HTTPException(status_code=400, detail="scores must be numeric")
    decision = PolicyService.decide(tool=tool, context=context, trust_score=trust_score, confidence_score=confidence_score)
    audit_log("OPS", "/ops/policy/decide", f"{tool}:{decision.get('decision')}", operation="READ", actor=_actor_label(auth))
    return {"tool": tool, "context": context, "trust_score": trust_score, "confidence_score": confidence_score, **decision}


@router.post("/model/recommend")
async def model_recommend(
    request: Request,
    body: dict,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    node_id = body.get("node_id", "unknown")
    node_type = body.get("node_type", "agent_task")
    config = body.get("config", {})

    from tools.gimo_server.ops_models import WorkflowNode
    from tools.gimo_server.services.model_router_service import ModelRouterService

    node = WorkflowNode(id=node_id, type=node_type, config=config)
    router_service = ModelRouterService()
    recommendation = router_service.promote_eco_mode(node)

    audit_log("OPS", "/ops/model/recommend", f"{node_id}", operation="READ", actor=_actor_label(auth))
    return recommendation
