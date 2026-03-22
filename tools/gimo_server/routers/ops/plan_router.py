
from __future__ import annotations
from typing import List, Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import OpsDraft, OpsPlan, OpsCreateDraftRequest, OpsUpdateDraftRequest
from tools.gimo_server.services.cognitive import CognitiveService
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.runtime_policy_service import RuntimePolicyService
from tools.gimo_server.services.intent_classification_service import IntentClassificationService
from tools.gimo_server.services.custom_plan_service import CustomPlanService
from .common import _require_role, _actor_label

router = APIRouter()

@router.get("/plan", response_model=OpsPlan, responses={404: {"description": "Plan not set"}})
async def get_plan(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
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
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    OpsService.set_plan(plan)
    audit_log("OPS", "/ops/plan", plan.id, operation="WRITE", actor=_actor_label(auth))
    return {"status": "ok"}

@router.get("/drafts", response_model=List[OpsDraft])
async def list_drafts(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    return OpsService.list_drafts(status=status, limit=limit, offset=offset)

def _build_draft_context_and_scope(body: OpsCreateDraftRequest):
    context = dict(body.context or {})
    if body.prompt and str(body.prompt).strip():
        prompt = str(body.prompt).strip()
        path_scope = list(context.get("repo_context", {}).get("path_scope", []))
    else:
        prompt = str(body.objective or "").strip()
        rc = dict(body.repo_context or {})
        ex = dict(body.execution or {})
        path_scope = list(rc.get("path_scope") or [])
        context.update({
            "constraints": list(body.constraints or []),
            "acceptance_criteria": list(body.acceptance_criteria or []),
            "repo_context": rc,
            "execution": ex,
            "intent_class": str(ex.get("intent_class") or ""),
            "contract_mode": "phase1",
        })
    return prompt, context, path_scope

def _evaluate_draft_intent(context: dict, path_scope: list, body: OpsCreateDraftRequest):
    policy_decision = RuntimePolicyService.evaluate_draft_policy(
        path_scope=path_scope,
        estimated_files_changed=context.get("estimated_files_changed"),
        estimated_loc_changed=context.get("estimated_loc_changed"),
    )
    declared_intent = str(context.get("intent_class") or "")
    raw_risk = context.get("risk_score")
    if raw_risk is None:
        raw_risk = (body.execution or {}).get("risk_score")
    try:
        risk_score = float(raw_risk or 0.0)
    except (TypeError, ValueError):
        risk_score = 0.0

    intent_decision = IntentClassificationService.evaluate(
        intent_declared=declared_intent,
        path_scope=path_scope,
        risk_score=risk_score,
        policy_decision=policy_decision.decision,
        policy_status_code=policy_decision.status_code,
    )
    return policy_decision, intent_decision

@router.post("/drafts", response_model=OpsDraft, status_code=201, responses={403: {"description": "Role required"}})
async def create_draft(
    request: Request,
    body: OpsCreateDraftRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    if auth.role not in ("actions", "operator", "admin"):
        raise HTTPException(status_code=403, detail="actions/operator/admin role required")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    
    prompt, context, path_scope = _build_draft_context_and_scope(body)
    policy_decision, intent_decision = _evaluate_draft_intent(context, path_scope, body)

    context.update({
        "policy_decision_id": policy_decision.policy_decision_id,
        "policy_decision": policy_decision.decision,
        "policy_status_code": policy_decision.status_code,
        "policy_hash_expected": policy_decision.policy_hash_expected,
        "policy_hash_runtime": policy_decision.policy_hash_runtime,
        "policy_triggered_rules": policy_decision.triggered_rules,
        "intent_declared": intent_decision.intent_declared,
        "intent_effective": intent_decision.intent_effective,
        "risk_score": intent_decision.risk_score,
        "decision_reason": intent_decision.decision_reason,
        "execution_decision": intent_decision.execution_decision,
    })

    if intent_decision.execution_decision in {"DRAFT_REJECTED_FORBIDDEN_SCOPE", "RISK_SCORE_TOO_HIGH"}:
        draft = OpsService.create_draft(prompt, context=context, status="rejected", error=intent_decision.execution_decision)
    else:
        draft = OpsService.create_draft(prompt, context=context)
    audit_log("OPS", "/ops/drafts", draft.id, operation="WRITE", actor=_actor_label(auth))
    return draft

@router.get("/drafts/{draft_id}", response_model=OpsDraft, responses={404: {"description": "Draft not found"}})
async def get_draft(
    request: Request,
    draft_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    draft = OpsService.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft

@router.put("/drafts/{draft_id}", response_model=OpsDraft, responses={404: {"description": "Value error"}})
async def update_draft(
    request: Request,
    draft_id: str,
    body: OpsUpdateDraftRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
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

@router.post("/drafts/{draft_id}/reject", response_model=OpsDraft, responses={403: {"description": "Role required"}, 404: {"description": "Value error"}})
async def reject_draft(
    request: Request,
    draft_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    if auth.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="admin/operator role required")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    try:
        updated = OpsService.reject_draft(draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/drafts/{draft_id}/reject", updated.id, operation="WRITE", actor=_actor_label(auth))
    return updated

@router.post("/slice0-pipeline", response_model=OpsDraft, status_code=201)
async def run_slice0_pipeline(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    prompt: Annotated[str, Query(..., min_length=1, max_length=8000)],
    repo_path: Annotated[str, Query(..., min_length=1)],
):
    """Ejecuta el Pipeline estilo LangGraph E2E (Slice 0/Anexo A)."""
    _require_role(auth, "operator")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    from tools.gimo_server.services.engine_service import EngineService
    try:
        # Create a draft first if needed, or assume a run is created
        draft = OpsService.create_draft(prompt, context={"repo_path": repo_path, "intent_effective": "SLICE0"})
        await EngineService.run_composition("slice0", draft.id, {"prompt": prompt, "repo_path": repo_path})
    except Exception as exc:
        # Fallback draft creation indicating error
        draft = OpsService.create_draft(
            prompt, provider=None, content=None, status="error", 
            error=f"Slice 0 Pipeline failed: {str(exc)[:200]}"
        )
    audit_log("OPS", "/ops/slice0-pipeline", draft.id, operation="WRITE", actor=_actor_label(auth))
    return draft

@router.post("/generate-plan", response_model=OpsDraft, status_code=201)
async def generate_structured_plan(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    prompt: Annotated[str, Query(..., min_length=1, max_length=8000)],
):
    """Generate a structured multi-task plan with Mermaid graph via LLM."""
    import json, re
    _require_role(auth, "operator")
    OpsService.set_gics(getattr(request.app.state, "gics", None))

    sys_prompt = (
        "You are a senior systems architect. Generate a JSON execution plan.\n"
        "RULES:\n"
        "- tasks[0] MUST have role 'Lead Orchestrator' with scope 'bridge'\n"
        "- Each worker task must have a unique id, title, description, and agent_assignee\n"
        "- agent_assignee must have: role, goal, backstory, model, system_prompt, instructions\n"
        "- Output ONLY valid JSON, no markdown, no explanations\n\n"
        f"Task: {prompt}\n\n"
        'JSON schema:\n'
        '{"id":"plan_...","title":"...","workspace":"...","created":"...","objective":"...",'
        '"tasks":[{"id":"t_orch","title":"[ORCH] ...","scope":"bridge","depends":[],"status":"pending",'
        '"description":"...","agent_assignee":{"role":"Lead Orchestrator","goal":"...","backstory":"...",'
        '"model":"qwen2.5-coder:3b","system_prompt":"...","instructions":["..."]}},'
        '{"id":"t_worker_1","title":"[WORKER] ...","scope":"file_write","depends":["t_orch"],'
        '"status":"pending","description":"...","agent_assignee":{...}}],"constraints":[]}\n'
    )
    try:
        resp = await ProviderService.static_generate(sys_prompt, context={"task_type": "disruptive_planning"})
        raw = resp.get("content", "").strip()
        raw = re.sub(r"```(?:json)?\s*\n?", "", raw).strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]
        plan_data = json.loads(raw)

        # Validate with OpsPlan for backwards compat
        plan = OpsPlan.model_validate(plan_data)

        # Create unified CustomPlan from LLM response
        custom_plan = CustomPlanService.create_plan_from_llm(
            plan_data, name=plan.title, description=plan.objective,
        )

        draft = OpsService.create_draft(
            prompt,
            content=plan.model_dump_json(indent=2),
            context={
                "structured": True,
                "custom_plan_id": custom_plan.id,
            },
            provider=resp.get("provider", "local_ollama"),
            status="draft",
        )
    except Exception as exc:
        draft = OpsService.create_draft(
            prompt, provider=None, content=None, status="error",
            error=f"Plan generation failed: {str(exc)[:180]}",
        )
    audit_log("OPS", "/ops/generate-plan", draft.id, operation="WRITE", actor=_actor_label(auth))
    return draft


async def _process_cognitive_generation(prompt: str, decision: Any, context_payload: dict):
    if decision.decision_path == "security_block":
        return OpsService.create_draft(
            prompt,
            context=context_payload,
            provider=None,
            content=None,
            status="error",
            error=(decision.error_actionable or "Solicitud bloqueada por seguridad")[:200],
        )
    if decision.can_bypass_llm and decision.direct_content:
        return OpsService.create_draft(
            prompt,
            context=context_payload,
            provider="cognitive_direct_response",
            content=decision.direct_content,
            status="draft",
        )
    
    resp = await ProviderService.static_generate(prompt, context={})
    provider_name = resp["provider"]
    content = resp["content"]
    
    _try_parse_custom_plan(content, prompt, context_payload)

    return OpsService.create_draft(
        prompt,
        context=context_payload,
        provider=provider_name,
        content=content,
        status="draft",
    )

def _try_parse_custom_plan(content: str, prompt: str, context_payload: dict) -> None:
    import json as _json
    try:
        raw_content = content.strip()
        if raw_content.startswith("{") or raw_content.startswith("["):
            parsed = _json.loads(raw_content)
            if isinstance(parsed, dict) and "tasks" in parsed:
                cp = CustomPlanService.create_plan_from_llm(parsed, name=prompt[:80])
                context_payload["structured"] = True
                context_payload["custom_plan_id"] = cp.id
    except Exception:
        pass

@router.post("/generate", response_model=OpsDraft, status_code=201)
async def generate_draft(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    prompt: Annotated[str, Query(..., min_length=1, max_length=8000)],
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

        draft = await _process_cognitive_generation(prompt, decision, context_payload)
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
