from __future__ import annotations

import hashlib
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext

from .ops_models import (
    OpsApproved,
    OpsApproveResponse,
    OpsConfig,
    OpsCreateDraftRequest,
    OpsCreateRunRequest,
    OpsDraft,
    OpsPlan,
    OpsRun,
    OpsUpdateDraftRequest,
    ProviderConfig,
)
from .services.ops_service import OpsService
from .services.provider_service import ProviderService


router = APIRouter(prefix="/ops", tags=["ops"])

# Role hierarchy: actions < operator < admin
_ROLE_LEVEL = {"actions": 0, "operator": 1, "admin": 2}


def _require_role(auth: AuthContext, minimum: Literal["operator", "admin"]) -> None:
    if _ROLE_LEVEL.get(auth.role, 0) < _ROLE_LEVEL[minimum]:
        raise HTTPException(status_code=403, detail=f"{minimum} role or higher required")


def _actor_label(auth: AuthContext) -> str:
    """Return a safe label for audit/storage — never the raw token."""
    short_hash = hashlib.sha256(auth.token.encode()).hexdigest()[:12]
    return f"{auth.role}:{short_hash}"


@router.get("/plan", response_model=OpsPlan)
async def get_plan(
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
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
    OpsService.set_plan(plan)
    audit_log("OPS", "/ops/plan", plan.id, operation="WRITE", actor=_actor_label(auth))
    return {"status": "ok"}


@router.get("/drafts", response_model=List[OpsDraft])
async def list_drafts(
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    return OpsService.list_drafts()


@router.post("/drafts", response_model=OpsDraft, status_code=201)
async def create_draft(
    request: Request,
    body: OpsCreateDraftRequest,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "admin")
    draft = OpsService.create_draft(body.prompt, context=body.context)
    audit_log("OPS", "/ops/drafts", draft.id, operation="WRITE", actor=_actor_label(auth))
    return draft


@router.get("/drafts/{draft_id}", response_model=OpsDraft)
async def get_draft(
    draft_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
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
    _require_role(auth, "admin")
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
    try:
        updated = OpsService.reject_draft(draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/drafts/{draft_id}/reject", updated.id, operation="WRITE", actor=_actor_label(auth))
    return updated


@router.post("/drafts/{draft_id}/approve", response_model=OpsApproveResponse)
async def approve_draft(
    request: Request,
    draft_id: str,
    auto_run: Optional[bool] = Query(None, description="Override default_auto_run from config"),
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "operator")
    actor = _actor_label(auth)
    try:
        approved = OpsService.approve_draft(draft_id, approved_by=actor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/drafts/{draft_id}/approve", approved.id, operation="WRITE", actor=actor)

    # Resolve auto_run: explicit param > config default
    should_run = auto_run if auto_run is not None else OpsService.get_config().default_auto_run
    run = None
    if should_run:
        try:
            run = OpsService.create_run(approved.id)
            audit_log("OPS", "/ops/runs", run.id, operation="WRITE_AUTO", actor=actor)
        except (PermissionError, ValueError):
            pass  # Non-fatal: approved was created, run creation failed silently
    return OpsApproveResponse(approved=approved, run=run)


@router.get("/approved", response_model=List[OpsApproved])
async def list_approved(
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    return OpsService.list_approved()


@router.get("/approved/{approved_id}", response_model=OpsApproved)
async def get_approved(
    approved_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    approved = OpsService.get_approved(approved_id)
    if not approved:
        raise HTTPException(status_code=404, detail="Approved entry not found")
    return approved


@router.post("/runs", response_model=OpsRun, status_code=201)
async def create_run(
    request: Request,
    body: OpsCreateRunRequest,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "operator")
    try:
        run = OpsService.create_run(body.approved_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", "/ops/runs", run.id, operation="WRITE", actor=_actor_label(auth))
    return run


@router.get("/runs", response_model=List[OpsRun])
async def list_runs(
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    return OpsService.list_runs()


@router.get("/runs/{run_id}", response_model=OpsRun)
async def get_run(
    run_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    run = OpsService.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/runs/{run_id}/cancel", response_model=OpsRun)
async def cancel_run(
    request: Request,
    run_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "operator")
    actor = _actor_label(auth)
    run = OpsService.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("done", "error", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Run already in terminal state: {run.status}")
    try:
        run = OpsService.update_run_status(run_id, "cancelled", msg=f"Cancelled by {actor}")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/runs/{run_id}/cancel", run.id, operation="WRITE", actor=actor)
    return run


@router.get("/provider", response_model=ProviderConfig)
async def get_provider(
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "admin")
    cfg = ProviderService.get_public_config()
    if not cfg:
        raise HTTPException(status_code=404, detail="Provider not configured")
    return cfg


@router.put("/provider", response_model=ProviderConfig)
async def set_provider(
    request: Request,
    config: ProviderConfig,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "admin")
    cfg = ProviderService.set_config(config)
    audit_log("OPS", "/ops/provider", "set", operation="WRITE", actor=_actor_label(auth))
    # return redacted version
    return ProviderService.get_public_config() or cfg


@router.post("/generate", response_model=OpsDraft, status_code=201)
async def generate_draft(
    request: Request,
    prompt: str = Query(..., min_length=1, max_length=8000),
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    # Generate requires admin, or operator if config allows it
    config = OpsService.get_config()
    if config.operator_can_generate:
        _require_role(auth, "operator")
    else:
        _require_role(auth, "admin")
    try:
        provider_name, content = await ProviderService.generate(prompt, context={})
        draft = OpsService.create_draft(
            prompt,
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


# ----- OPS Config -----


@router.get("/config", response_model=OpsConfig)
async def get_config(
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "operator")
    return OpsService.get_config()


@router.put("/config", response_model=OpsConfig)
async def set_config(
    request: Request,
    config: OpsConfig,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    _require_role(auth, "admin")
    result = OpsService.set_config(config)
    audit_log("OPS", "/ops/config", "set", operation="WRITE", actor=_actor_label(auth))
    return result


# ----- Filtered OpenAPI for external integrations -----

# Paths safe for actions/operator tokens (GET-only read endpoints).
_ACTIONS_SAFE_PATHS = {
    "/ops/plan", "/ops/drafts", "/ops/approved", "/ops/runs",
    "/ops/config", "/status", "/tree", "/file", "/search", "/diff",
    "/ui/status",
}
_ACTIONS_SAFE_PATH_PREFIXES = (
    "/ops/drafts/", "/ops/approved/", "/ops/runs/",
)


@router.get("/openapi.json")
async def get_filtered_openapi(
    request: Request,
    auth: AuthContext = Depends(verify_token),
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

    new_paths = {}
    for path, methods in filtered.get("paths", {}).items():
        is_safe = path in _ACTIONS_SAFE_PATHS or any(
            path.startswith(p) for p in _ACTIONS_SAFE_PATH_PREFIXES
        )
        if is_safe:
            # Keep only GET methods for actions-safe paths
            safe_methods = {m: v for m, v in methods.items() if m == "get"}
            if safe_methods:
                new_paths[path] = safe_methods

    # Also include the approve and runs POST for operator-level spec
    if _ROLE_LEVEL.get(auth.role, 0) >= _ROLE_LEVEL["operator"]:
        for path in ("/ops/drafts/{draft_id}/approve", "/ops/runs"):
            if path in filtered.get("paths", {}):
                entry = new_paths.setdefault(path, {})
                if "post" in filtered["paths"][path]:
                    entry["post"] = filtered["paths"][path]["post"]

    filtered["paths"] = new_paths
    filtered["info"]["title"] = "Repo Orchestrator API (Actions)"
    filtered["info"]["description"] = "Filtered spec for external integrations. Admin-only endpoints excluded."
    return filtered
