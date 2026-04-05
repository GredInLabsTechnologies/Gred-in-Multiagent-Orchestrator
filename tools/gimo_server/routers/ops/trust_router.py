from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from ...ops_models import CircuitBreakerConfigModel
from ...services.storage_service import StorageService
from ...services.trust_engine import TrustEngine
from ...services.institutional_memory_service import InstitutionalMemoryService
from ...services.ops_service import OpsService
from .common import _require_role, _actor_label

router = APIRouter()

@router.post("/trust/query")
async def trust_query(
    request: Request,
    body: dict,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    dimension_key = str(body.get("dimension_key", "")).strip()
    if not dimension_key:
        raise HTTPException(status_code=400, detail="dimension_key is required")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    engine = TrustEngine(storage.trust)
    result = engine.query_dimension(dimension_key)
    audit_log("OPS", "/ops/trust/query", dimension_key, operation="READ", actor=_actor_label(auth))
    return result

@router.get("/trust/dashboard")
async def trust_dashboard(
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    request: Request,
    limit: int = Query(100, ge=1, le=500),
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    engine = TrustEngine(storage.trust)
    result = engine.dashboard(limit=limit)
    audit_log("OPS", "/ops/trust/dashboard", str(limit), operation="READ", actor=_actor_label(auth))
    return {"items": result, "count": len(result)}

@router.get("/trust/suggestions")
async def trust_suggestions(
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    request: Request,
    limit: int = Query(20, ge=1, le=200),
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    service = InstitutionalMemoryService(storage)
    items = service.generate_suggestions(limit=limit)
    audit_log("OPS", "/ops/trust/suggestions", str(limit), operation="READ", actor=_actor_label(auth))
    return {"items": items, "count": len(items)}

@router.get("/trust/circuit-breaker/{dimension_key}")
async def get_circuit_breaker_config(
    request: Request,
    dimension_key: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    result = storage.get_circuit_breaker_config(dimension_key)
    if result is None:
        engine = TrustEngine(storage.trust)
        cfg = engine.circuit_breaker
        result = {
            "dimension_key": dimension_key,
            "window": cfg.window,
            "failure_threshold": cfg.failure_threshold,
            "recovery_probes": cfg.recovery_probes,
            "cooldown_seconds": cfg.cooldown_seconds,
        }
    audit_log("OPS", f"/ops/trust/circuit-breaker/{dimension_key}", dimension_key, operation="READ", actor=_actor_label(auth))
    return result

@router.put("/trust/circuit-breaker/{dimension_key}")
async def set_circuit_breaker_config(
    request: Request,
    dimension_key: str,
    body: CircuitBreakerConfigModel,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    result = storage.upsert_circuit_breaker_config(dimension_key, body.model_dump())
    audit_log("OPS", f"/ops/trust/circuit-breaker/{dimension_key}", f"{dimension_key}:updated", operation="WRITE", actor=_actor_label(auth))
    return result
@router.post("/trust/reset")
async def trust_reset(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Reset threat state (operator level — consistent with other trust endpoints)."""
    _require_role(auth, "operator")
    from ...security import save_security_db, threat_engine
    threat_engine.clear_all()
    save_security_db()
    audit_log("OPS", "/ops/trust/reset", "clear_all", operation="WRITE", actor=_actor_label(auth))
    return {"status": "success", "message": "Threat level reset to NOMINAL"}


@router.get("/trust/ids/events")
async def get_ids_events(
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    agent_id: Annotated[Optional[str], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
):
    """Retrieve IDS agent action events."""
    _require_role(auth, "operator")
    # Using OpsService access to telemetry
    if not OpsService._telemetry:
         return {"items": [], "count": 0}
    events = OpsService._telemetry.list_events(agent_id=agent_id, limit=limit)
    return {"items": [e.model_dump() for e in events], "count": len(events)}


@router.get("/trust/ids/insights")
async def get_ids_insights(
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    agent_id: Annotated[Optional[str], Query()] = None,
):
    """Retrieve structural recommendations for agent governance."""
    _require_role(auth, "operator")
    insights = OpsService.get_agent_insights(agent_id=agent_id)
    return {"items": insights, "count": len(insights)}
