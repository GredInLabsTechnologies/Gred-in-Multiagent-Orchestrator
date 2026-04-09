
from __future__ import annotations
import asyncio
import json
import logging
from typing import List, Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import OpsDraft, OpsPlan, OpsCreateDraftRequest, OpsUpdateDraftRequest
from tools.gimo_server.services.cognitive import CognitiveService
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.providers.service import ProviderService
from tools.gimo_server.services.runtime_policy_service import RuntimePolicyService
from tools.gimo_server.services.intent_classification_service import IntentClassificationService
from tools.gimo_server.services.custom_plan_service import CustomPlanService
from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService
from .common import _require_role, _actor_label

router = APIRouter()
logger = logging.getLogger("orchestrator.routers.ops.plan")

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
        operator_class=context.get("operator_class", "human_ui"),
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
    operator_class: Annotated[str, Query()] = "human_ui",
):
    """Generate a structured multi-task plan with Mermaid graph via LLM."""
    import json, re, time
    from tools.gimo_server.services.timeout.duration_telemetry_service import DurationTelemetryService

    # GAEP Phase 1: Start timing
    start_time = time.time()

    _require_role(auth, "operator")
    OpsService.set_gics(getattr(request.app.state, "gics", None))

    # Inject GICS into telemetry service
    DurationTelemetryService.set_gics(getattr(request.app.state, "gics", None))

    # Build contract to ensure schema alignment
    from tools.gimo_server.services.contract_factory import ContractFactory
    contract = ContractFactory.build(auth, request)

    # Get orchestrator memorandum (SOTA + GICS insights)
    from tools.gimo_server.services.orchestrator_memorandum_service import OrchestratorMemorandumService
    memorandum = OrchestratorMemorandumService.build_memorandum(include_gics=True)

    # Generate system prompt from contract schema (SINGLE SOURCE OF TRUTH)
    roles_str = contract.format_roles_for_prompt()
    sys_prompt = (
        "You are a senior systems architect for GIMO (Gred-In Multiagent Orchestrator). "
        "Generate a JSON execution plan for the following task.\n\n"
        "## CRITICAL RULES (MUST FOLLOW):\n\n"
        "1. **EXACTLY ONE ORCHESTRATOR**: The plan MUST have exactly ONE task with role='orchestrator'. "
        "This is the coordination node that manages the workflow.\n\n"
        "2. **ROLE CONSTRAINTS**: agent_assignee.role MUST be exactly one of: " + roles_str + "\n"
        "   - 'orchestrator': Coordinates and delegates to workers (EXACTLY 1 per plan)\n"
        "   - 'worker': Executes specific tasks (can be multiple)\n\n"
        "**SCOPE CONSTRAINT**: Generate AT MOST 5 workers for simple tasks (single file, small utility, calculator, etc). "
        "NEVER include tasks for: deployment, production monitoring, user manuals, packaging as executable, "
        "or code review with other developers — unless the user EXPLICITLY requested them. "
        "Keep plans minimal and proportionate to the task complexity.\n\n"
        f"3. **MODEL SPECIFICATION**: agent_assignee.model MUST be: \"{contract.model_id}\"\n\n"
        "4. **TASK STRUCTURE**: Each task needs:\n"
        "   - id: Unique identifier (e.g., 't_orch', 't_worker_1')\n"
        "   - title: Descriptive title prefixed with [ORCH] or [WORKER]\n"
        "   - scope: Task scope (e.g., 'bridge', 'file_write', 'file_edit')\n"
        "   - description: Detailed description of what the agent should do\n"
        "   - depends: Array of task IDs this task depends on (workers depend on orchestrator)\n"
        "   - agent_assignee: Agent configuration object\n\n"
        "5. **AGENT ASSIGNEE STRUCTURE**: Each agent_assignee needs:\n"
        "   - role: Agent role (orchestrator or worker)\n"
        "   - goal: Primary objective for this agent\n"
        "   - backstory: Context and capabilities\n"
        "   - model: Model identifier\n"
        "   - system_prompt: Detailed instructions for the agent\n"
        "   - instructions: Array of specific steps\n\n"
        "6. **DEPENDENCY GRAPH**: Workers MUST depend on orchestrator. Dependencies must form a valid DAG.\n\n"
        "7. **OUTPUT FORMAT**: Output ONLY valid JSON, no markdown code blocks, no explanations.\n\n"
        + (f"\n{memorandum}\n\n" if memorandum else "") +
        f"## USER TASK:\n{prompt}\n\n"
        "## JSON SCHEMA EXAMPLE:\n"
        '{"id":"plan_...","title":"...","workspace":"...","created":"...","objective":"...",'
        '"tasks":[{"id":"t_orch","title":"[ORCH] Coordinate task execution","scope":"bridge","depends":[],"status":"pending",'
        f'"description":"Orchestrate the execution of workers","agent_assignee":{{"role":"orchestrator","goal":"Coordinate workflow","backstory":"Senior coordinator",'
        f'"model":"{contract.model_id}","system_prompt":"You are the orchestrator...","instructions":["Analyze task","Delegate to workers","Monitor progress"]}},'
        '{"id":"t_worker_1","title":"[WORKER] Execute specific task","scope":"file_write","depends":["t_orch"],'
        f'"status":"pending","description":"Perform actual work","agent_assignee":{{"role":"worker","goal":"Complete assigned task","backstory":"Specialist worker",'
        f'"model":"{contract.model_id}","system_prompt":"You are a worker...","instructions":["Follow orchestrator instructions"]}}],"constraints":[]}}\n\n'
        "Now generate the plan as valid JSON:"
    )
    try:
        # Respect X-Preferred-Model header
        preferred_model = request.headers.get("X-Preferred-Model")
        context = {"task_type": "disruptive_planning"}
        if preferred_model:
            context["model"] = preferred_model
        resp = await ProviderService.static_generate(sys_prompt, context=context)
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
        canonical_plan = TaskDescriptorService.canonicalize_plan_data(plan_data)

        # Create unified CustomPlan from LLM response
        custom_plan = CustomPlanService.create_plan_from_llm(
            canonical_plan, name=plan.title, description=plan.objective,
        )

        # Validate plan scope: reject absurdly large plans
        task_count = len(canonical_plan.get("tasks", plan_data.get("tasks", [])))
        if task_count > 10:
            logger.warning("Plan has %d tasks — pruning to first 10", task_count)
            tasks_key = "tasks" if "tasks" in canonical_plan else None
            if tasks_key:
                canonical_plan[tasks_key] = canonical_plan[tasks_key][:10]

        draft = OpsService.create_draft(
            prompt,
            content=TaskDescriptorService.canonicalize_plan_content(canonical_plan),
            context={
                "structured": True,
                "custom_plan_id": custom_plan.id,
                "execution_decision": "AUTO_RUN_ELIGIBLE",
                "operator_class": operator_class,
            },
            provider=resp.get("provider", "local_ollama"),
            status="draft",
        )
    except Exception as exc:
        draft = OpsService.create_draft(
            prompt, provider=None, content=None, status="error",
            error=f"Plan generation failed: {str(exc)[:180]}",
        )

    # GAEP Phase 1: Record duration telemetry
    duration = time.time() - start_time
    try:
        DurationTelemetryService.record_operation_duration(
            operation="plan",
            duration=duration,
            context={
                "model": contract.model_id,
                "prompt_length": len(prompt),
                "provider": resp.get("provider") if 'resp' in locals() else "unknown",
                "structured": True,
            },
            success=(draft.status == "draft")
        )
    except Exception as telemetry_exc:
        logger.warning("Failed to record plan duration telemetry: %s", telemetry_exc)

    audit_log("OPS", "/ops/generate-plan", draft.id, operation="WRITE", actor=_actor_label(auth))
    return draft


@router.post("/generate-plan-stream")
async def generate_plan_stream(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    prompt: Annotated[str, Query(..., min_length=1, max_length=8000)],
):
    """
    Generate a structured multi-task plan with SSE progress streaming (SEA Phase 3).

    Returns Server-Sent Events (SSE) stream with progress updates:
    - started: Operation initiated with ETA
    - progress: Progress updates (stage, percentage, elapsed, remaining)
    - checkpoint: Checkpoint saved (resumable)
    - completed: Operation completed with result
    - error: Error occurred
    """
    import json, re, time
    from tools.gimo_server.services.timeout.duration_telemetry_service import DurationTelemetryService
    from tools.gimo_server.services.timeout.adaptive_timeout_service import AdaptiveTimeoutService
    from tools.gimo_server.services.timeout.progress_emitter import ProgressEmitter

    _require_role(auth, "operator")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    DurationTelemetryService.set_gics(getattr(request.app.state, "gics", None))

    async def event_generator():
        """SSE event generator."""
        try:
            # Build contract
            from tools.gimo_server.services.contract_factory import ContractFactory
            contract = ContractFactory.build(auth, request)

            # Predict duration
            AdaptiveTimeoutService.set_gics(getattr(request.app.state, "gics", None))
            estimated_duration = AdaptiveTimeoutService.predict_timeout(
                operation="plan",
                context={
                    "model": contract.model_id,
                    "prompt_length": len(prompt),
                }
            )

            # Helper to emit SSE event
            def emit_sse(event_type: str, data: dict) -> str:
                """Format SSE event."""
                event_data = json.dumps(data)
                return f"event: {event_type}\ndata: {event_data}\n\n"

            # Emit started
            yield emit_sse("started", {
                "operation": "plan",
                "estimated_duration": estimated_duration,
                "model": contract.model_id,
            })

            # Start timing
            start_time = time.time()

            # Progress: analyzing prompt (10%)
            yield emit_sse("progress", {
                "stage": "analyzing_prompt",
                "progress": 0.1,
                "elapsed": round(time.time() - start_time, 1),
                "remaining": round(estimated_duration * 0.9, 1),
            })

            await asyncio.sleep(0.1)  # Small delay for UX

            # Get memorandum
            from tools.gimo_server.services.orchestrator_memorandum_service import OrchestratorMemorandumService
            memorandum = OrchestratorMemorandumService.build_memorandum(include_gics=True)

            # Progress: building context (20%)
            yield emit_sse("progress", {
                "stage": "building_context",
                "progress": 0.2,
                "elapsed": round(time.time() - start_time, 1),
                "remaining": round(estimated_duration * 0.8, 1),
            })

            # Build system prompt
            roles_str = contract.format_roles_for_prompt()
            sys_prompt = (
                "You are a senior systems architect for GIMO (Gred-In Multiagent Orchestrator). "
                "Generate a JSON execution plan for the following task.\n\n"
                "## CRITICAL RULES (MUST FOLLOW):\n\n"
                "1. **EXACTLY ONE ORCHESTRATOR**: The plan MUST have exactly ONE task with role='orchestrator'. "
                "This is the coordination node that manages the workflow.\n\n"
                "2. **ROLE CONSTRAINTS**: agent_assignee.role MUST be exactly one of: " + roles_str + "\n"
                "   - 'orchestrator': Coordinates and delegates to workers (EXACTLY 1 per plan)\n"
                "   - 'worker': Executes specific tasks (can be multiple)\n\n"
                f"3. **MODEL SPECIFICATION**: agent_assignee.model MUST be: \"{contract.model_id}\"\n\n"
                "4. **TASK STRUCTURE**: Each task needs:\n"
                "   - id: Unique identifier (e.g., 't_orch', 't_worker_1')\n"
                "   - title: Descriptive title prefixed with [ORCH] or [WORKER]\n"
                "   - scope: Task scope (e.g., 'bridge', 'file_write', 'file_edit')\n"
                "   - description: Detailed description of what the agent should do\n"
                "   - depends: Array of task IDs this task depends on (workers depend on orchestrator)\n"
                "   - agent_assignee: Agent configuration object\n\n"
                "5. **AGENT ASSIGNEE STRUCTURE**: Each agent_assignee needs:\n"
                "   - role: Agent role (orchestrator or worker)\n"
                "   - goal: Primary objective for this agent\n"
                "   - backstory: Context and capabilities\n"
                "   - model: Model identifier\n"
                "   - system_prompt: Detailed instructions for the agent\n"
                "   - instructions: Array of specific steps\n\n"
                "6. **DEPENDENCY GRAPH**: Workers MUST depend on orchestrator. Dependencies must form a valid DAG.\n\n"
                "7. **OUTPUT FORMAT**: Output ONLY valid JSON, no markdown code blocks, no explanations.\n\n"
                + (f"\n{memorandum}\n\n" if memorandum else "") +
                f"## USER TASK:\n{prompt}\n\n"
                "Now generate the plan as valid JSON:"
            )

            # Progress: calling LLM (40%)
            yield emit_sse("progress", {
                "stage": "calling_llm",
                "progress": 0.4,
                "elapsed": round(time.time() - start_time, 1),
                "remaining": round(estimated_duration * 0.6, 1),
            })

            # Call LLM with REAL heartbeat — yield events in real time via asyncio.Queue
            preferred_model = request.headers.get("X-Preferred-Model")
            context = {"task_type": "disruptive_planning"}
            if preferred_model:
                context["model"] = preferred_model

            # Queue-based pattern: provider task and heartbeat task push events;
            # generator yields them as they arrive (real-time, not buffered).
            event_queue: asyncio.Queue = asyncio.Queue()
            _SENTINEL_DONE = object()
            _SENTINEL_ERR = object()

            async def _provider_call():
                try:
                    result = await ProviderService.static_generate(sys_prompt, context=context)
                    await event_queue.put((_SENTINEL_DONE, result))
                except Exception as exc:
                    await event_queue.put((_SENTINEL_ERR, exc))

            async def _heartbeat():
                tick = 0
                try:
                    while True:
                        await asyncio.sleep(15)
                        tick += 1
                        await event_queue.put(("hb", tick))
                except asyncio.CancelledError:
                    pass

            provider_task = asyncio.create_task(_provider_call())
            heartbeat_task = asyncio.create_task(_heartbeat())
            resp = None
            provider_exc: Exception | None = None
            try:
                while True:
                    kind, payload = await event_queue.get()
                    if kind == "hb":
                        yield emit_sse("progress", {
                            "stage": "waiting_for_provider",
                            "message": f"Waiting for provider response... ({payload * 15}s)",
                            "progress": min(0.4 + payload * 0.03, 0.65),
                            "elapsed": round(time.time() - start_time, 1),
                        })
                    elif kind is _SENTINEL_DONE:
                        resp = payload
                        break
                    elif kind is _SENTINEL_ERR:
                        provider_exc = payload
                        break
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except (asyncio.CancelledError, Exception):
                    pass
                if not provider_task.done():
                    provider_task.cancel()
                    try:
                        await provider_task
                    except (asyncio.CancelledError, Exception):
                        pass

            if provider_exc is not None:
                raise provider_exc

            raw = resp.get("content", "").strip()

            # Progress: parsing response (70%)
            yield emit_sse("progress", {
                "stage": "parsing_response",
                "progress": 0.7,
                "elapsed": round(time.time() - start_time, 1),
                "remaining": round(estimated_duration * 0.3, 1),
            })

            # Parse JSON
            raw = re.sub(r"```(?:json)?\s*\n?", "", raw).strip()
            if raw.endswith("```"):
                raw = raw[:-3].strip()
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start:end + 1]
            plan_data = json.loads(raw)

            # Progress: validating plan (85%)
            yield emit_sse("progress", {
                "stage": "validating_plan",
                "progress": 0.85,
                "elapsed": round(time.time() - start_time, 1),
                "remaining": round(estimated_duration * 0.15, 1),
            })

            # Validate with OpsPlan
            plan = OpsPlan.model_validate(plan_data)
            canonical_plan = TaskDescriptorService.canonicalize_plan_data(plan_data)

            # Create unified CustomPlan
            custom_plan = CustomPlanService.create_plan_from_llm(
                canonical_plan, name=plan.title, description=plan.objective,
            )

            # Create draft
            draft = OpsService.create_draft(
                prompt,
                content=TaskDescriptorService.canonicalize_plan_content(canonical_plan),
                context={
                    "structured": True,
                    "custom_plan_id": custom_plan.id,
                    "execution_decision": "AUTO_RUN_ELIGIBLE",
                },
                provider=resp.get("provider", "local_ollama"),
                status="draft",
            )

            # Record telemetry
            duration = time.time() - start_time
            try:
                DurationTelemetryService.record_operation_duration(
                    operation="plan",
                    duration=duration,
                    context={
                        "model": contract.model_id,
                        "prompt_length": len(prompt),
                        "provider": resp.get("provider"),
                        "structured": True,
                        "streaming": True,
                    },
                    success=True
                )
            except Exception:
                pass

            # Emit completed
            yield emit_sse("completed", {
                "result": {
                    "draft_id": draft.id,
                    "custom_plan_id": custom_plan.id,
                    "task_count": len(plan.tasks),
                    "content": draft.content,
                    "status": draft.status,
                },
                "duration": round(duration, 1),
                "status": "success",
            })

            audit_log("OPS", "/ops/generate-plan-stream", draft.id, operation="WRITE", actor=_actor_label(auth))

        except Exception as exc:
            logger.exception("Stream generation failed")

            # Emit error
            yield emit_sse("error", {
                "error": str(exc)[:200],
                "error_code": type(exc).__name__,
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


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
    content = _try_parse_custom_plan(resp["content"], prompt, context_payload)

    return OpsService.create_draft(
        prompt,
        context=context_payload,
        provider=provider_name,
        content=content,
        status="draft",
    )

def _try_parse_custom_plan(content: str, prompt: str, context_payload: dict) -> str:
    import json as _json
    try:
        raw_content = content.strip()
        if raw_content.startswith("{") or raw_content.startswith("["):
            parsed = _json.loads(raw_content)
            if isinstance(parsed, dict) and "tasks" in parsed:
                canonical_plan = TaskDescriptorService.canonicalize_plan_data(parsed)
                cp = CustomPlanService.create_plan_from_llm(canonical_plan, name=prompt[:80])
                context_payload["structured"] = True
                context_payload["custom_plan_id"] = cp.id
                return TaskDescriptorService.canonicalize_plan_content(canonical_plan)
    except Exception:
        pass
    return content

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
