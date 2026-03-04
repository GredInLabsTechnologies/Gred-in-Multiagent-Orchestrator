import re
import os

def refactor_plan_router():
    path = "c:\\Users\\shilo\\Documents\\Github\\gred_in_multiagent_orchestrator\\tools\\gimo_server\\routers\\ops\\plan_router.py"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # extract context setup from create_draft
    create_draft_original = r'''@router\.post\("/drafts", response_model=OpsDraft, status_code=201, responses={403: {"description": "Role required"}}\)
async def create_draft\(.*?return draft
'''

    create_draft_new = """def _build_draft_context_and_scope(body: OpsCreateDraftRequest):
    if body.prompt and str(body.prompt).strip():
        prompt = str(body.prompt).strip()
        context = dict(body.context or {})
        path_scope = list((context.get("repo_context") or {}).get("path_scope") or [])
    else:
        prompt = str(body.objective or "").strip()
        context = dict(body.context or {})
        path_scope = list((body.repo_context or {}).get("path_scope") or [])
        context.update({
            "constraints": list(body.constraints or []),
            "acceptance_criteria": list(body.acceptance_criteria or []),
            "repo_context": dict(body.repo_context or {}),
            "execution": dict(body.execution or {}),
            "intent_class": str((body.execution or {}).get("intent_class") or ""),
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
    rl: Annotated[None, Depends(check_rate_limit)],
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
"""
    content = re.sub(create_draft_original, create_draft_new, content, flags=re.DOTALL)

    generate_draft_original = r'''@router\.post\("/generate", response_model=OpsDraft, status_code=201\)
async def generate_draft\(.*?return draft
'''
    
    generate_draft_new = """async def _process_cognitive_generation(prompt: str, decision: Any, context_payload: dict):
    if decision.decision_path == "security_block":
        return OpsService.create_draft(
            prompt,
            context=context_payload,
            provider=None,
            content=None,
            status="error",
            error=(decision.error_actionable or "Solicitud bloqueada por seguridad")[:200],
        )
    elif decision.can_bypass_llm and decision.direct_content:
        return OpsService.create_draft(
            prompt,
            context=context_payload,
            provider="cognitive_direct_response",
            content=decision.direct_content,
            status="draft",
        )
    else:
        import json as _json
        resp = await ProviderService.static_generate(prompt, context={})
        provider_name = resp["provider"]
        content = resp["content"]

        custom_plan_id = None
        try:
            raw_content = content.strip()
            if raw_content.startswith("{") or raw_content.startswith("["):
                parsed = _json.loads(raw_content)
                if isinstance(parsed, dict) and "tasks" in parsed:
                    cp = CustomPlanService.create_plan_from_llm(parsed, name=prompt[:80])
                    custom_plan_id = cp.id
                    context_payload["structured"] = True
        except Exception:
            pass

        if custom_plan_id:
            context_payload["custom_plan_id"] = custom_plan_id

        return OpsService.create_draft(
            prompt,
            context=context_payload,
            provider=provider_name,
            content=content,
            status="draft",
        )

@router.post("/generate", response_model=OpsDraft, status_code=201)
async def generate_draft(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
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
"""
    content = re.sub(generate_draft_original, generate_draft_new, content, flags=re.DOTALL)

    import inspect
    from typing import Any
    content = "from typing import Any\n" + content.replace("from typing import List, Annotated", "from typing import List, Annotated, Any")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    refactor_plan_router()
    print("Refactored plan router")
