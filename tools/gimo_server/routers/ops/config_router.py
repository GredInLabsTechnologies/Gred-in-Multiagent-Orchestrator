from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import ProviderConfig, OpsConfig, ProviderSelectionRequest
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.provider_service import ProviderService
from .common import _require_role, _actor_label

router = APIRouter()


@router.get("/provider", response_model=ProviderConfig, responses={404: {"description": "Not Found"}})
async def get_provider(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    cfg = ProviderService.get_public_config()
    if not cfg:
        raise HTTPException(status_code=404, detail="Provider not configured")
    return cfg


@router.get("/provider/capabilities")
async def get_provider_capabilities(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    matrix = ProviderService.get_capability_matrix()
    audit_log("OPS", "/ops/provider/capabilities", str(len(matrix)), operation="READ", actor=_actor_label(auth))
    return {"items": matrix, "count": len(matrix)}


@router.put("/provider", response_model=ProviderConfig)
async def set_provider(
    request: Request,
    config: ProviderConfig,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    cfg = ProviderService.set_config(config)
    audit_log("OPS", "/ops/provider", "set", operation="WRITE", actor=_actor_label(auth))
    return ProviderService.get_public_config() or cfg


@router.post("/provider/select", response_model=ProviderConfig)
async def select_provider(
    request: Request,
    payload: ProviderSelectionRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    try:
        cfg = await ProviderService.select_provider(
            provider_id=payload.provider_id,
            model=payload.model,
            prefer_family=payload.prefer_family,
            api_key=payload.api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_log("OPS", "/ops/provider/select", payload.provider_id, operation="WRITE", actor=_actor_label(auth))
    return ProviderService.get_public_config() or cfg


@router.get("/provider/recommendation")
async def provider_recommendation(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    from tools.gimo_server.services.recommendation_service import RecommendationService

    recommendation = await RecommendationService.get_recommendation()
    audit_log("OPS", "/ops/provider/recommendation", recommendation.get("provider", "unknown"), operation="READ", actor=_actor_label(auth))
    return recommendation


@router.get("/connectors")
async def list_connectors(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = ProviderService.list_connectors()
    audit_log("OPS", "/ops/connectors", str(data.get("count", 0)), operation="READ", actor=_actor_label(auth))
    return data


@router.get("/connectors/{connector_id}/health", responses={404: {"description": "Not Found"}})
async def connector_health(
    request: Request,
    connector_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    provider_id: str | None = None,
):
    _require_role(auth, "operator")
    try:
        data = await ProviderService.connector_health(connector_id, provider_id=provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/connectors/{connector_id}/health", connector_id, operation="READ", actor=_actor_label(auth))
    return data


@router.get("/config", response_model=OpsConfig)
async def get_config(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    return OpsService.get_config()


@router.put("/config", response_model=OpsConfig)
async def set_config(
    request: Request,
    config: OpsConfig,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    result = OpsService.set_config(config)
    audit_log("OPS", "/ops/config", "set", operation="WRITE", actor=_actor_label(auth))
    return result


@router.get("/cost/compare")
async def compare_costs(
    model_a: Annotated[str, Query(..., min_length=1)],
    model_b: Annotated[str, Query(..., min_length=1)],
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    from tools.gimo_server.services.economy.cost_service import CostService
    try:
        return CostService.get_impact_comparison(model_a, model_b)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
