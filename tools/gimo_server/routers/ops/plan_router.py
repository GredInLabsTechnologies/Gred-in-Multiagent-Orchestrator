from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import OpsDraft, OpsPlan, OpsCreateDraftRequest, OpsUpdateDraftRequest
from tools.gimo_server.services.cognitive import CognitiveService
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.provider_service import ProviderService
from .common import _require_role, _actor_label

router = APIRouter()

@router.get("/plan", response_model=OpsPlan)
async def get_plan(
    request: Request,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    plan = OpsService.get_plan()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not set")
    return plan

@router.put("/plan")
async def set_plan(
    request: Request,
    plan: OpsPlan,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "admin")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    OpsService.set_plan(plan)
    audit_log("OPS", "/ops/plan", plan.id, operation="WRITE", actor=_actor_label(auth))
    return {"status": "ok"}

@router.get("/drafts", response_model=List[OpsDraft])
async def list_drafts(
    request: Request,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    return OpsService.list_drafts()

@router.post("/drafts", response_model=OpsDraft, status_code=201)
async def create_draft(
    request: Request,
    body: OpsCreateDraftRequest,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "admin")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    draft = OpsService.create_draft(body.prompt, context=body.context)
    audit_log("OPS", "/ops/drafts", draft.id, operation="WRITE", actor=_actor_label(auth))
    return draft

@router.get("/drafts/{draft_id}", response_model=OpsDraft)
async def get_draft(
    request: Request,
    draft_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    draft = OpsService.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft

@router.put("/drafts/{draft_id}", response_model=OpsDraft)
async def update_draft(
    request: Request,
    draft_id: str,
    body: OpsUpdateDraftRequest,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "operator")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    try:
        updated = OpsService.update_draft(
            draft_id, prompt=body.prompt, content=body.content, context=body.context
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/drafts/{draft_id}", updated.id, operation="WRITE", actor=_actor_label(auth))
    return updated

@router.post("/drafts/{draft_id}/reject", response_model=OpsDraft)
async def reject_draft(
    request: Request,
    draft_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "admin")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    try:
        updated = OpsService.reject_draft(draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/drafts/{draft_id}/reject", updated.id, operation="WRITE", actor=_actor_label(auth))
    return updated

@router.post("/generate", response_model=OpsDraft, status_code=201)
async def generate_draft(
    request: Request,
    prompt: str = Query(..., min_length=1, max_length=8000),
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    config = OpsService.get_config()
    if config.operator_can_generate:
        _require_role(auth, "operator")
    else:
        _require_role(auth, "admin")
    cognitive = CognitiveService()
    try:
        OpsService.set_gics(getattr(request.app.state, "gics", None))
        decision = cognitive.evaluate(prompt, context={"prompt": prompt})
        context_payload = dict(decision.context_updates)
        context_payload.setdefault("detected_intent", decision.intent.name)
        context_payload.setdefault("decision_path", decision.decision_path)
        context_payload.setdefault("can_bypass_llm", decision.can_bypass_llm)
        if decision.error_actionable:
            context_payload.setdefault("error_actionable", decision.error_actionable)

        if decision.decision_path == "security_block":
            draft = OpsService.create_draft(
                prompt,
                context=context_payload,
                provider=None,
                content=None,
                status="error",
                error=(decision.error_actionable or "Solicitud bloqueada por seguridad")[:200],
            )
        elif decision.can_bypass_llm and decision.direct_content:
            draft = OpsService.create_draft(
                prompt,
                context=context_payload,
                provider="cognitive_direct_response",
                content=decision.direct_content,
                status="draft",
            )
        else:
            resp = await ProviderService.static_generate(prompt, context={})
            provider_name = resp["provider"]
            content = resp["content"]
            draft = OpsService.create_draft(
                prompt,
                context=context_payload,
                provider=provider_name,
                content=content,
                status="draft",
            )
    except Exception as exc:
        draft = OpsService.create_draft(
            prompt,
            provider=None,
            content=None,
            status="error",
            error=str(exc)[:200],
        )
    audit_log("OPS", "/ops/generate", draft.id, operation="WRITE", actor=_actor_label(auth))
    return draft
