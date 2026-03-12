from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Annotated
from fastapi.responses import StreamingResponse
import asyncio
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from .routers.ops import (
    plan_router, run_router, eval_router, trust_router, config_router, observability_router, mastery_router, skills_router, custom_plan_router, conversation_router, hitl_router,
    provider_auth_router, catalog_router, tools_router, policy_router, dependencies_router,
)

router = APIRouter(prefix="/ops", tags=["ops"])

# Mount sub-routers
router.include_router(plan_router.router)
router.include_router(run_router.router)
router.include_router(eval_router.router)
router.include_router(trust_router.router)
router.include_router(config_router.router)
router.include_router(provider_auth_router.router)
router.include_router(catalog_router.router)
router.include_router(tools_router.router)
router.include_router(policy_router.router)
router.include_router(dependencies_router.router)
router.include_router(observability_router.router)
router.include_router(mastery_router.router)
router.include_router(skills_router.router)
router.include_router(custom_plan_router.router)
router.include_router(conversation_router.router)
router.include_router(hitl_router.router)

# Phase 9 — Actions-Safe public contract (strict allowlist)
_ACTIONS_SAFE_PUBLIC_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("post", "/ops/drafts"),
    ("post", "/ops/drafts/{draft_id}/approve"),
    ("get", "/ops/runs/{run_id}"),
    ("get", "/ops/runs/{run_id}/preview"),
    ("get", "/ui/repos"),
    ("get", "/ui/repos/active"),
    ("post", "/ui/repos/select"),
)

@router.get("/openapi.json", responses={404: {"description": "Not found"}})
async def get_filtered_openapi(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    """Return a filtered OpenAPI spec with only actions-safe endpoints.

    Useful for ChatGPT Actions import — excludes admin-only endpoints
    like /ops/provider, /ops/generate, PUT /ops/plan, etc.
    """
    import copy
    import yaml
    from pathlib import Path as P

    spec_path = P(__file__).parent / "openapi.yaml"
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="OpenAPI spec not found")
    full_spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    filtered = copy.deepcopy(full_spec)

    source_paths = filtered.get("paths", {}) or {}
    new_paths: dict[str, dict] = {}

    # Keep the public contract deterministic and fail-fast if the source spec drifts.
    for method, path in _ACTIONS_SAFE_PUBLIC_ENDPOINTS:
        if path not in source_paths:
            raise HTTPException(status_code=404, detail=f"Public spec path missing: {path}")
        source_methods = source_paths.get(path) or {}
        if method not in source_methods:
            raise HTTPException(status_code=404, detail=f"Public spec method missing: {method.upper()} {path}")
        entry = new_paths.setdefault(path, {})
        entry[method] = source_methods[method]

    filtered["paths"] = new_paths
    filtered["info"]["title"] = "Repo Orchestrator API (Actions)"
    filtered["info"]["description"] = "Filtered spec for external integrations. Admin-only endpoints excluded."
    return filtered

@router.get("/stream")
async def ops_event_stream(request: Request):
    """
    Subscribes to the global GIMO SSE stream.
    Used by Master Orchestrators (IDE, Agents) to receive asynchronous 
    events, such as 'handover_required' or 'agent_doubt'.
    """
    from tools.gimo_server.services.notification_service import NotificationService
    
    async def event_generator():
        # Suscribir cliente a la cola
        queue = await NotificationService.subscribe()
        try:
            while True:
                # Comprobar si el cliente se desconectó
                if await request.is_disconnected():
                    break
                
                # Esperamos mensajes (usamos timeout corto para chequear is_disconnected)
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive opcional, o simplemente pasamos
                    yield ": keep-alive\n\n"
                    
        finally:
            # Limpiamos cuando el stream se cae
            NotificationService.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
