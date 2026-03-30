from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Annotated
from fastapi.responses import StreamingResponse
import asyncio
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.operator_status_service import OperatorStatusService
from tools.gimo_server.routers.ops.common import _require_role
from .routers.ops import (
    plan_router, run_router, eval_router, trust_router, config_router, observability_router, mastery_router, skills_router, custom_plan_router, conversation_router, hitl_router,
    provider_auth_router, catalog_router, tools_router, policy_router, dependencies_router,
    web_search_router, child_run_router, capability_router, inference_router, app_router,
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
router.include_router(web_search_router.router)
router.include_router(child_run_router.router)
router.include_router(capability_router.router)
router.include_router(inference_router.router)
router.include_router(app_router.router)

# Phase 9 — Actions-Safe public contract (strict allowlist)
_ACTIONS_SAFE_PUBLIC_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("post", "/ops/drafts"),
    ("post", "/ops/drafts/{draft_id}/approve"),
    ("get", "/ops/runs/{run_id}"),
    ("get", "/ops/runs/{run_id}/preview"),
    ("get", "/ops/repos"),
    ("get", "/ops/repos/active"),
    ("get", "/ops/app/repos"),
    ("post", "/ops/app/sessions"),
    ("get", "/ops/app/sessions/{id}"),
    ("post", "/ops/app/sessions/{id}/repo/select"),
    ("post", "/ops/app/sessions/{id}/purge"),
    ("get", "/ops/app/runs/{run_id}/review"),
    ("post", "/ops/app/runs/{run_id}/discard"),
    # Phase 5A: Recon & Draft Semantics
    ("get", "/ops/app/sessions/{id}/recon/list"),
    ("get", "/ops/app/sessions/{id}/recon/search"),
    ("get", "/ops/app/sessions/{id}/recon/read/{file_handle}"),
    ("post", "/ops/app/sessions/{id}/drafts"),
    # Phase 5A: Context Requests
    ("post", "/ops/app/sessions/{id}/context-requests"),
    ("get", "/ops/app/sessions/{id}/context-requests"),
    ("post", "/ops/app/sessions/{id}/context-requests/{req_id}/resolve"),
    ("post", "/ops/app/sessions/{id}/context-requests/{req_id}/cancel"),
)

@router.get("/openapi.json", responses={404: {"description": "Not found"}})
async def get_filtered_openapi(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    """[LEGACY INTEGRATION] Return a filtered OpenAPI spec with only actions-safe endpoints.

    Note: This is provided for backward compatibility with external integrations 
    like ChatGPT Actions. The /mcp/app façade is the preferred modern entry point.
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
    filtered["info"]["title"] = "GIMO Core (Legacy Actions-Safe)"
    filtered["info"]["description"] = "Legacy filtered spec for external integrations. Official façade is at /mcp/app."
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


@router.get("/operator/status")
async def get_operator_status(auth: Annotated[AuthContext, Depends(verify_token)]):
    """
    P2: Returns a single backend-authored snapshot for operator status.
    """
    _require_role(auth, "operator")
    return OperatorStatusService.get_status_snapshot()


@router.get("/capabilities")
async def get_capabilities(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    """Returns server capabilities for CLI bond handshake.

    Includes role, plan (from session if Firebase), and feature list.
    This is the single source of truth for what the CLI can do.
    """
    from tools.gimo_server.version import __version__
    from tools.gimo_server.security.auth import SESSION_COOKIE_NAME, session_store

    plan = "local"  # default for local tokens

    # If Firebase session exists, extract plan
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie:
        session = session_store.validate(cookie)
        if session and session.plan:
            plan = session.plan

    return {
        "version": __version__,
        "role": auth.role,
        "plan": plan,
        "features": ["plans", "runs", "chat", "threads", "mastery", "trust", "observe"],
    }


@router.get("/notices")
async def get_notices(auth: Annotated[AuthContext, Depends(verify_token)]):
    """
    F2: returns a canonical backend-authored notice feed for all surfaces.
    """
    _require_role(auth, "operator")
    from tools.gimo_server.services.notice_policy_service import NoticePolicyService
    # Evaluation is backend-authored based on the authoritative status snapshot.
    status = OperatorStatusService.get_status_snapshot()
    return NoticePolicyService.evaluate_all(status)


@router.get("/notifications/stream")
async def ops_notifications_event_stream(request: Request):
    """Backward-compatible SSE endpoint alias for legacy UI clients."""
    return await ops_event_stream(request)
