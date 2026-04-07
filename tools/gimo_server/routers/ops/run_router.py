from __future__ import annotations
from typing import List, Optional, Annotated
import asyncio
import logging

logger = logging.getLogger("ops.run_router")
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import (
    ActionDraft,
    OpsApproved, OpsApproveResponse, OpsRun, OpsCreateRunRequest,
    WorkflowExecuteRequest, WorkflowGraph, WorkflowCheckpoint
)
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.hitl_gate_service import HitlGateService
from tools.gimo_server.services.storage_service import StorageService
from tools.gimo_server.services.graph_engine import GraphEngine
from tools.gimo_server.services.observability_service import ObservabilityService
from tools.gimo_server.services.confidence_service import ConfidenceService
from tools.gimo_server.services.trust_engine import TrustEngine
from tools.gimo_server.services.engine_service import EngineService
from tools.gimo_server.engine.journal import RunJournal
from tools.gimo_server.resilience import SupervisedTask


def _spawn_run(request: Request, run_id: str, composition: str | None = None) -> "asyncio.Task | None":
    """Launch a run via the supervisor (or a tracked fallback) and return the task.

    Status-after-ack contract (R17 Cluster A): callers must NOT transition the run
    to ``running`` until this helper returns successfully. If the spawned task is
    already done with an exception (synchronous failure), this raises ``RuntimeError``
    so the caller can keep the run in ``pending`` and surface the error to the worker.
    """
    supervisor: SupervisedTask | None = getattr(request.app.state, "supervisor", None)

    async def _on_failure(exc: Exception) -> None:
        try:
            OpsService.update_run_status(run_id, "error", msg=f"Execution failed: {str(exc)[:200]}")
        except Exception as status_exc:
            logger.error("on_failure handler error for run %s: %s", run_id, status_exc)

    if supervisor:
        task = supervisor.spawn(
            EngineService.execute_run(run_id, composition=composition),
            name=f"run:{run_id}",
            on_failure=_on_failure,
            timeout=3600,
        )
    else:
        # Fallback: no supervisor (e.g. tests) — still handle failures.
        # Track via SupervisedTask process-wide registry for lifespan drain.
        async def _fallback() -> None:
            try:
                await EngineService.execute_run(run_id, composition=composition)
            except Exception as exc:
                await _on_failure(exc)
                raise
        task = asyncio.create_task(_fallback())
        try:
            task.set_name(f"run:{run_id}")  # type: ignore[attr-defined]
        except Exception:
            pass
        if isinstance(task, asyncio.Task):
            SupervisedTask.register_external(task)

    # Verify the spawn did not synchronously fail with an exception. A task that
    # is already done at this point indicates a configuration / coroutine error,
    # not a normal completion (real execute_run is async and yields immediately).
    # Some test paths monkeypatch asyncio.create_task to return None — treat
    # that as opaque success (the test owns the lifecycle).
    if task is not None and isinstance(task, asyncio.Task) and task.done():
        exc = task.exception() if not task.cancelled() else None
        if exc is not None:
            raise RuntimeError(f"Spawn failed for run {run_id}: {exc}")
    return task
from tools.gimo_server.engine.replay import ReplayEngine
from tools.gimo_server.engine.pipeline import Pipeline
from .common import _require_role, _actor_label, _WORKFLOW_ENGINES

router = APIRouter()

RUN_NOT_FOUND = "Run not found"


@router.get("/action-drafts", response_model=List[ActionDraft])
async def list_action_drafts(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    status: Annotated[Optional[str], Query(description="Filter by status")] = None,
):
    _require_role(auth, "operator")
    return HitlGateService.list_drafts(status=status)


@router.post(
    "/action-drafts/{draft_id}/approve", 
    response_model=ActionDraft,
    responses={404: {"description": "Action draft not found"}}
)
async def approve_action_draft(
    request: Request,
    draft_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    reason: Annotated[Optional[str], Query(description="Optional reason")] = None,
):
    _require_role(auth, "operator")
    try:
        draft = await HitlGateService.approve(draft_id, reason=reason)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/action-drafts/{draft_id}/approve", draft.id, operation="WRITE", actor=_actor_label(auth))
    return draft


@router.post(
    "/action-drafts/{draft_id}/reject", 
    response_model=ActionDraft,
    responses={404: {"description": "Action draft not found"}}
)
async def reject_action_draft(
    request: Request,
    draft_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    reason: Annotated[Optional[str], Query(description="Optional reason")] = None,
):
    _require_role(auth, "operator")
    try:
        draft = await HitlGateService.reject(draft_id, reason=reason)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/action-drafts/{draft_id}/reject", draft.id, operation="WRITE", actor=_actor_label(auth))
    return draft

@router.post(
    "/drafts/{draft_id}/approve", 
    response_model=OpsApproveResponse,
    responses={404: {"description": "Draft not found"}, 409: {"description": "Risk score too high"}}
)
async def approve_draft(
    request: Request,
    draft_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    auto_run: Annotated[Optional[bool], Query(description="Override default_auto_run from config")] = None,
):
    _require_role(auth, "operator")
    actor = _actor_label(auth)
    OpsService.set_gics(getattr(request.app.state, "gics", None))

    draft = OpsService.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    context = dict(draft.context or {})
    execution_decision = str(context.get("execution_decision") or "")

    if execution_decision == "RISK_SCORE_TOO_HIGH":
        # Ensure draft is rejected if risk is too high and we try to approve
        try:
            OpsService.reject_draft(draft_id)
        except Exception:
            pass
        raise HTTPException(status_code=409, detail="RISK_SCORE_TOO_HIGH")

    try:
        approved = OpsService.approve_draft(draft_id, approved_by=actor)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409 if isinstance(exc, RuntimeError) else 404, detail=str(exc))
    
    audit_log("OPS", f"/ops/drafts/{draft_id}/approve", approved.id, operation="WRITE", actor=actor)

    run = None
    config = OpsService.get_config()
    intent_effective = str(context.get("intent_effective") or "").upper()
    excluded_intents = [i.upper() for i in (config.auto_run_excluded_intents or [])]
    auto_run_blocked_by_intent = intent_effective in excluded_intents

    explicit_auto = auto_run is True  # caller explicitly requested execution
    should_run = (
        (auto_run if auto_run is not None else config.default_auto_run)
        and (explicit_auto or execution_decision == "AUTO_RUN_ELIGIBLE")
        and not auto_run_blocked_by_intent
    )

    if auto_run_blocked_by_intent and (auto_run is True or config.default_auto_run):
        # Audit: auto_run was requested but blocked by intent exclusion policy.
        audit_log(
            "OPS", f"/ops/drafts/{draft_id}/approve", approved.id,
            operation="AUTO_RUN_BLOCKED",
            actor=actor,
        )

    if should_run:
        try:
            run = OpsService.create_run(approved.id)
            audit_log("OPS", "/ops/runs", run.id, operation="WRITE_AUTO", actor=actor)
            
            composition = "custom_plan" if context.get("custom_plan_id") else None
            if run.status == "pending":
                # R17 Cluster A: status-after-ack — spawn FIRST, then transition.
                try:
                    _spawn_run(request, run.id, composition=composition)
                    run = OpsService.update_run_status(run.id, "running", msg="Execution started via draft approval auto-run")
                except Exception as exc:
                    logger.error("Spawn failed for draft %s, falling back to worker: %s", draft_id, exc)
                    try:
                        worker = getattr(request.app.state, "run_worker", None)
                        if worker is not None:
                            worker.notify()
                    except Exception as wk_exc:
                        logger.error("Worker fallback also failed for draft %s: %s", draft_id, wk_exc)
            else:
                _spawn_run(request, run.id, composition=composition)
            
            if composition:
                audit_log("OPS", f"/ops/{composition}s/{context.get('custom_plan_id')}/execute", run.id, operation="WRITE_AUTO", actor=actor)
        except RuntimeError as exc:
            detail = str(exc)
            if detail.startswith("RUN_ALREADY_ACTIVE:"):
                existing_id = detail.split(":")[1]
                run = OpsService.get_run(existing_id)
            else:
                pass
        except Exception as exc:
            logger.error("Auto-run creation failed for draft %s: %s", draft_id, exc)

    return OpsApproveResponse(approved=approved, run=run)

@router.get("/approved", response_model=List[OpsApproved])
async def list_approved(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    return OpsService.list_approved()

@router.get(
    "/approved/{approved_id}", 
    response_model=OpsApproved,
    responses={404: {"description": "Approved entry not found"}}
)
async def get_approved(
    request: Request,
    approved_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    approved = OpsService.get_approved(approved_id)
    if not approved:
        raise HTTPException(status_code=404, detail="Approved entry not found")
    return approved

@router.post(
    "/runs", 
    response_model=OpsRun, 
    status_code=201,
    responses={
        403: {"description": "Permission denied"},
        404: {"description": "Approved plan not found"},
        409: {"description": "Active run conflict"},
        422: {"description": "Invalid lifecycle transition"},
    }
)
async def create_run(
    request: Request,
    body: OpsCreateRunRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    try:
        run = OpsService.create_run(body.approved_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        detail = str(exc)
        if detail.startswith("RUN_ALREADY_ACTIVE"):
            raise HTTPException(status_code=409, detail=detail)
        if detail.startswith("INVALID_FSM_TRANSITION") or detail.startswith("CANNOT_TRANSITION"):
            raise HTTPException(status_code=422, detail=detail)
        raise HTTPException(status_code=409, detail=f"RUN_CONTRACT_VIOLATION:{detail[:120]}")

    # Deterministic immediate start from any channel (UI/MCP) when run is pending.
    # We intentionally start merge-gate directly and set status to running to avoid
    # pending limbo and worker race on the same run.
    if run.status == "pending":
        # R17 Cluster A: status-after-ack — spawn FIRST, then transition.
        try:
            _spawn_run(request, run.id)
            run = OpsService.update_run_status(run.id, "running", msg="Execution started via /ops/runs")
        except Exception as exc:
            logger.error("Spawn failed for run %s, falling back to worker: %s", run.id, exc)
            try:
                worker = getattr(request.app.state, "run_worker", None)
                if worker is not None:
                    worker.notify()
            except Exception as wk_exc:
                logger.error("Worker fallback also failed for run %s: %s", run.id, wk_exc)

    audit_log("OPS", "/ops/runs", run.id, operation="WRITE", actor=_actor_label(auth))
    return run

@router.get("/runs", response_model=List[OpsRun])
async def list_runs(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    return OpsService.list_runs()

@router.get(
    "/runs/{run_id}", 
    response_model=OpsRun,
    responses={404: {"description": RUN_NOT_FOUND}}
)
async def get_run(
    request: Request,
    run_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    run = OpsService.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)
    return run


@router.get(
    "/runs/{run_id}/events",
    responses={404: {"description": RUN_NOT_FOUND}},
)
async def get_run_events(
    request: Request,
    run_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Stream run log entries as SSE events."""
    from starlette.responses import StreamingResponse
    import json as _json

    OpsService.set_gics(getattr(request.app.state, "gics", None))
    run = OpsService.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)

    async def _generate():
        # 1. Stage-level events from the run journal (structured pipeline telemetry)
        journal_path = OpsService.OPS_DIR / "run_journals" / f"{run_id}.jsonl"
        journal_events: list[dict] = []
        if journal_path.exists():
            try:
                for line in journal_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = _json.loads(line)
                        entry.setdefault("source", "journal")
                        journal_events.append(entry)
                    except _json.JSONDecodeError:
                        continue
            except OSError:
                pass

        # 2. Coarse-grained run.log entries (free-text status messages)
        log_events: list[dict] = []
        for entry in (getattr(run, "log", None) or []):
            data = entry if isinstance(entry, dict) else {"msg": str(entry)}
            data.setdefault("source", "run_log")
            log_events.append(data)

        # 3. Chronological merge. Journal entries use `started_at` (ISO8601 datetime),
        # run.log uses `ts` (epoch float). Normalize both to a comparable float seconds.
        from datetime import datetime as _dt
        def _ts_key(e: dict) -> float:
            for field in ("started_at", "ts", "timestamp", "finished_at"):
                v = e.get(field)
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str):
                    try:
                        return _dt.fromisoformat(v.replace("Z", "+00:00")).timestamp()
                    except ValueError:
                        continue
            return 0.0
        merged = sorted(journal_events + log_events, key=_ts_key)

        for i, data in enumerate(merged):
            yield f"id: {i}\ndata: {_json.dumps(data, default=str)}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@router.post(
    "/runs/{run_id}/replay",
    responses={404: {"description": RUN_NOT_FOUND}},
)
async def replay_run(
    request: Request,
    run_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    from_step: Annotated[str, Query(..., description="Stage step id to replay from")],
):
    _require_role(auth, "operator")
    run = OpsService.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)

    journal_path = str((OpsService.OPS_DIR / "run_journals" / f"{run_id}.jsonl"))
    journal = RunJournal(storage_path=journal_path)
    journal.load()
    replay = ReplayEngine(journal)

    # Replay currently returns deterministic journal slice. Pipeline provided for API contract.
    output = await replay.replay_from(from_step, Pipeline(run_id=run_id, stages=[]))
    return {
        "run_id": run_id,
        "from_step": from_step,
        "status": output.status,
        "artifacts": output.artifacts,
        "error": output.error,
    }


@router.post(
    "/runs/{run_id}/rerun",
    response_model=OpsRun,
    status_code=201,
    responses={
        404: {"description": RUN_NOT_FOUND},
        409: {"description": "Active run conflict"},
        422: {"description": "Invalid lifecycle transition"},
    },
)
async def rerun(
    request: Request,
    run_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    try:
        run = OpsService.rerun(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        detail = str(exc)
        if detail.startswith("RUN_ALREADY_ACTIVE") or detail.startswith("RERUN_SOURCE_ACTIVE"):
            raise HTTPException(status_code=409, detail=detail)
        if detail.startswith("INVALID_FSM_TRANSITION") or detail.startswith("CANNOT_TRANSITION"):
            raise HTTPException(status_code=422, detail=detail)
        raise HTTPException(status_code=409, detail=f"RUN_CONTRACT_VIOLATION:{detail[:120]}")

    if run.status == "pending":
        # R17 Cluster A: status-after-ack — spawn FIRST, then transition.
        try:
            _spawn_run(request, run.id)
            run = OpsService.update_run_status(run.id, "running", msg="Execution started via /ops/runs/{run_id}/rerun")
        except Exception as exc:
            logger.error("Rerun spawn failed for run %s, falling back to worker: %s", run_id, exc)
            try:
                worker = getattr(request.app.state, "run_worker", None)
                if worker is not None:
                    worker.notify()
            except Exception as wk_exc:
                logger.error("Rerun worker fallback also failed for run %s: %s", run_id, wk_exc)

    audit_log("OPS", f"/ops/runs/{run_id}/rerun", run.id, operation="WRITE", actor=_actor_label(auth))
    return run


@router.get("/runs/{run_id}/preview", responses={404: {"description": RUN_NOT_FOUND}})
async def get_run_preview(
    request: Request,
    run_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    request_id = str(
        getattr(request.state, "request_id", "")
        or request.headers.get("X-Request-ID", "")
        or request.headers.get("X-Correlation-ID", "")
    )
    trace_id = str(
        request.headers.get("X-Trace-ID", "")
        or request.query_params.get("trace_id", "")
    )
    preview = OpsService.get_run_preview(run_id, request_id=request_id, trace_id=trace_id)
    if not preview:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)

    ObservabilityService.record_structured_event(
        event_type="run_preview_read",
        status=str(preview.get("final_status") or preview.get("status") or ""),
        trace_id=str(preview.get("trace_id") or trace_id),
        request_id=str(preview.get("request_id") or request_id),
        run_id=str(preview.get("run_id") or run_id),
        actor=_actor_label(auth),
        intent_class=str(preview.get("intent_effective") or ""),
        repo_id="",
        baseline_version=str(preview.get("baseline_version") or ""),
        model_attempted=str(preview.get("model_attempted") or ""),
        final_model_used=str(preview.get("final_model_used") or ""),
        stage="preview",
        latency_ms=0.0,
        error_category="",
    )
    return preview

@router.post(
    "/runs/{run_id}/cancel", 
    response_model=OpsRun,
    responses={
        404: {"description": RUN_NOT_FOUND},
        409: {"description": "Run already in terminal state"}
    }
)
async def cancel_run(
    request: Request,
    run_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    actor = _actor_label(auth)
    run = OpsService.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)
    if run.status in ("done", "error", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Run already in terminal state: {run.status}")
    try:
        OpsService.set_gics(getattr(request.app.state, "gics", None))
        run = OpsService.update_run_status(run_id, "cancelled", msg=f"Cancelled by {actor}")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/runs/{run_id}/cancel", run.id, operation="WRITE", actor=actor)
    return run

@router.post(
    "/runs/{run_id}/merge",
    response_model=OpsRun,
    responses={
        404: {"description": RUN_NOT_FOUND},
        400: {"description": "Run is not in AWAITING_MERGE status"},
        409: {"description": "Manual merge failed"}
    }
)
async def perform_manual_merge(
    run_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    from tools.gimo_server.services.merge_gate_service import MergeGateService
    
    run = OpsService.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)
    if run.status != "AWAITING_MERGE":
        raise HTTPException(status_code=400, detail="Run is not in AWAITING_MERGE status")
    
    success = await MergeGateService.perform_manual_merge(run_id)
    updated_run = OpsService.get_run(run_id)
    
    if not success:
        # The service updates status to MERGE_CONFLICT or ROLLBACK_EXECUTED
        raise HTTPException(status_code=409, detail="Manual merge failed")
        
    audit_log("OPS", f"/ops/runs/{run_id}/merge", run_id, operation="WRITE", actor=_actor_label(auth))
    return updated_run

@router.post("/workflows/execute")
async def execute_workflow(
    request: Request,
    body: WorkflowExecuteRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    engine = GraphEngine(
        body.workflow,
        storage=storage,
        persist_checkpoints=bool(body.persist_checkpoints),
        workflow_timeout_seconds=body.workflow_timeout_seconds,
        confidence_service=ConfidenceService(TrustEngine(storage)),
    )
    _WORKFLOW_ENGINES[body.workflow.id] = engine
    state = await engine.execute(initial_state=body.initial_state)
    audit_log("OPS", "/ops/workflows/execute", body.workflow.id, operation="WRITE", actor=_actor_label(auth))
    return {
        "workflow_id": body.workflow.id,
        "checkpoint_count": len(state.checkpoints),
        "paused": bool(state.data.get("execution_paused", False)),
        "aborted_reason": state.data.get("aborted_reason"),
        "state": state.model_dump(),
    }

@router.get("/workflows/{workflow_id}/checkpoints")
async def list_workflow_checkpoints(
    request: Request,
    workflow_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    items = storage.list_checkpoints(workflow_id)
    audit_log("OPS", f"/ops/workflows/{workflow_id}/checkpoints", str(len(items)), operation="READ", actor=_actor_label(auth))
    return {"items": items, "count": len(items)}

@router.post(
    "/workflows/{workflow_id}/resume",
    responses={
        404: {"description": "Workflow not found"},
        409: {"description": "No checkpoints available"},
        400: {"description": "Resume failed"},
        500: {"description": "Invalid persisted workflow"}
    }
)
async def resume_workflow(
    request: Request,
    workflow_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    from_checkpoint: Annotated[int, Query(description="Checkpoint index to resume from (default: last)")] = -1,
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    engine = _WORKFLOW_ENGINES.get(workflow_id)
    if engine is None:
        persisted = storage.get_workflow(workflow_id)
        if not persisted or not isinstance(persisted.get("data"), dict):
            raise HTTPException(status_code=404, detail="Workflow not found")
        try:
            workflow = WorkflowGraph.model_validate(persisted["data"])
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Invalid persisted workflow: {exc}")
        engine = GraphEngine(
            workflow, 
            storage=storage, 
            persist_checkpoints=True,
            confidence_service=ConfidenceService(TrustEngine(storage)),
        )
        raw_checkpoints = storage.list_checkpoints(workflow_id)
        engine.state.checkpoints = [WorkflowCheckpoint.model_validate(item) for item in raw_checkpoints]
        if engine.state.checkpoints:
            engine.state.data = dict(engine.state.checkpoints[-1].state)
        _WORKFLOW_ENGINES[workflow_id] = engine
    if not engine.state.checkpoints:
        raise HTTPException(status_code=409, detail="No checkpoints available to resume")
    try:
        next_node = engine.resume_from_checkpoint(from_checkpoint)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    state = await engine.execute()
    audit_log("OPS", f"/ops/workflows/{workflow_id}/resume", f"checkpoint={from_checkpoint}", operation="WRITE", actor=_actor_label(auth))
    return {
        "workflow_id": workflow_id,
        "resumed_from_checkpoint": from_checkpoint,
        "next_node": next_node,
        "checkpoint_count": len(state.checkpoints),
        "state": state.model_dump(),
    }
