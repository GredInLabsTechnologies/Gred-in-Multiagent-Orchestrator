from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import ProviderConfig, OpsConfig, ProviderSelectionRequest
from tools.gimo_server.ops_models import ProviderUpsertRequest
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.providers.service import ProviderService
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


@router.post("/provider/upsert", response_model=ProviderConfig)
async def upsert_provider(
    request: Request,
    payload: ProviderUpsertRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    try:
        cfg = ProviderService.upsert_provider_entry(
            provider_id=payload.provider_id,
            provider_type=payload.provider_type,
            display_name=payload.display_name,
            base_url=payload.base_url,
            api_key=payload.api_key,
            auth_mode=payload.auth_mode,
            auth_ref=payload.auth_ref,
            model=payload.model,
            activate=payload.activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_log("OPS", "/ops/provider/upsert", payload.provider_id, operation="WRITE", actor=_actor_label(auth))
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


@router.get("/connectors/health")
async def connectors_health_aggregate(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Aggregate health check across all connectors."""
    _require_role(auth, "operator")
    connectors = ProviderService.list_connectors()
    items = connectors.get("connectors", [])
    results = []
    for c in items:
        cid = c.get("id", "unknown")
        try:
            health = await ProviderService.connector_health(cid)
            results.append({"id": cid, "healthy": health.get("healthy", False), **health})
        except Exception:
            results.append({"id": cid, "healthy": False, "error": "health check failed"})
    healthy_count = sum(1 for r in results if r.get("healthy"))
    audit_log("OPS", "/ops/connectors/health", str(len(results)), operation="READ", actor=_actor_label(auth))
    return {"total": len(results), "healthy": healthy_count, "connectors": results}


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


# ---------------------------------------------------------------------------
# Model Context Registry — agents self-report token limits
# ---------------------------------------------------------------------------

@router.get("/models/context-limits")
async def get_context_limits(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Return the full model context registry.

    The registry maps 'provider_id:model' → max_tokens (int).
    Entries are written by the agentic loop (auto-discovery) or by agents
    via PUT /ops/models/context-limits.
    """
    _require_role(auth, "operator")
    from tools.gimo_server.services.agentic_loop_service import AgenticLoopService
    registry = AgenticLoopService._load_context_registry()
    return {"items": registry, "count": len(registry)}


@router.put("/models/context-limits")
async def register_context_limit(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Register a model's token limit in the context registry.

    Body: {"provider_id": "groq", "model": "qwen/qwen3-32b", "max_tokens": 6000}

    This is the REST interface for agents to self-report their capacity.
    The agentic loop reads this registry via _get_context_budget() to adapt
    message trimming, tool compaction, and retry behavior.
    """
    _require_role(auth, "operator")
    body = await request.json()
    provider_id = body.get("provider_id", "").strip()
    model = body.get("model", "").strip()
    max_tokens = int(body.get("max_tokens", 0))
    if not provider_id or not model:
        raise HTTPException(status_code=400, detail="provider_id and model are required")
    if max_tokens <= 0:
        raise HTTPException(status_code=400, detail="max_tokens must be a positive integer")

    from tools.gimo_server.services.agentic_loop_service import AgenticLoopService
    AgenticLoopService.register_model_context_limit(provider_id, model, max_tokens)
    audit_log("OPS", "/ops/models/context-limits", f"{provider_id}:{model}={max_tokens}", operation="WRITE", actor=_actor_label(auth))
    return {"status": "registered", "key": f"{provider_id}:{model}", "max_tokens": max_tokens}
