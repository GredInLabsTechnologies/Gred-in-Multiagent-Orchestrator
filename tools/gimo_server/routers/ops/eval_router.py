from __future__ import annotations
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import EvalRunRequest, EvalRunReport, EvalRunSummary, EvalRunDetail, EvalDataset
from tools.gimo_server.services.storage_service import StorageService
from tools.gimo_server.services.evals_service import EvalsService
from .common import _require_role, _actor_label

router = APIRouter()

@router.post("/evals/run", response_model=EvalRunReport)
async def evals_run(
    request: Request,
    body: EvalRunRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
    fail_on_gate: bool = Query(False, description="If true and gate fails, returns HTTP 412"),
):
    _require_role(auth, "operator")
    if body.dataset.workflow_id != body.workflow.id:
        raise HTTPException(status_code=400, detail="dataset.workflow_id must match workflow.id")
    report = await EvalsService.run_regression(
        workflow=body.workflow,
        dataset=body.dataset,
        judge=body.judge,
        gate=body.gate,
        case_limit=body.case_limit,
    )
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    report_id = storage.save_eval_report(report)
    report.eval_run_id = report_id
    audit_log("OPS", "/ops/evals/run", f"{report.workflow_id}:{report.passed_cases}/{report.total_cases}", operation="WRITE", actor=_actor_label(auth))
    if fail_on_gate and not report.gate_passed:
        raise HTTPException(status_code=412, detail=report.model_dump())
    return report

@router.get("/evals/runs", response_model=List[EvalRunSummary])
async def list_eval_runs(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
    workflow_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    rows = storage.list_eval_reports(workflow_id=workflow_id, limit=limit)
    audit_log("OPS", "/ops/evals/runs", str(len(rows)), operation="READ", actor=_actor_label(auth))
    return rows

@router.get("/evals/runs/{run_id}", response_model=EvalRunDetail)
async def get_eval_run(
    request: Request,
    run_id: int,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    item = storage.get_eval_report(run_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Eval run not found")
    report = item.get("report") if isinstance(item, dict) else None
    if isinstance(report, dict):
        report.setdefault("eval_run_id", item.get("run_id"))
    payload = {
        "run_id": item.get("run_id"),
        "workflow_id": item.get("workflow_id"),
        "created_at": item.get("created_at"),
        "report": report,
    }
    audit_log("OPS", f"/ops/evals/runs/{run_id}", str(run_id), operation="READ", actor=_actor_label(auth))
    return payload

@router.post("/evals/datasets")
async def create_eval_dataset(
    request: Request,
    dataset: EvalDataset,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
    version_tag: Optional[str] = Query(None, max_length=128),
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    dataset_id = storage.save_eval_dataset(dataset, version_tag=version_tag)
    audit_log("OPS", "/ops/evals/datasets", f"{dataset.workflow_id}:{dataset_id}", operation="WRITE", actor=_actor_label(auth))
    return {"dataset_id": dataset_id, "workflow_id": dataset.workflow_id, "version_tag": version_tag}

@router.get("/evals/datasets")
async def list_eval_datasets(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
    workflow_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    items = storage.list_eval_datasets(workflow_id=workflow_id, limit=limit)
    audit_log("OPS", "/ops/evals/datasets", str(len(items)), operation="READ", actor=_actor_label(auth))
    return {"items": items, "count": len(items)}

@router.get("/evals/datasets/{dataset_id}")
async def get_eval_dataset(
    request: Request,
    dataset_id: int,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    storage = StorageService(gics=getattr(request.app.state, "gics", None))
    item = storage.get_eval_dataset(dataset_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Eval dataset not found")
    audit_log("OPS", f"/ops/evals/datasets/{dataset_id}", str(dataset_id), operation="READ", actor=_actor_label(auth))
    return item
