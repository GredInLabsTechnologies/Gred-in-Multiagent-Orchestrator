from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import CliDependencyInstallRequest
from tools.gimo_server.services.providers.service import ProviderService
from .common import _require_role, _actor_label

router = APIRouter()


@router.get("/system/dependencies")
async def list_system_dependencies(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await ProviderService.list_cli_dependencies()
    gics = getattr(request.app.state, "gics", None)
    failure = getattr(gics, "last_start_failure", None) if gics is not None else None
    if failure is not None:
        data["gics_failure_reason"] = failure.reason
        data["gics_failure_message"] = failure.message
        if failure.detail is not None:
            data["gics_failure_detail"] = failure.detail
    audit_log("OPS", "/ops/system/dependencies", str(data.get("count", 0)), operation="READ", actor=_actor_label(auth))
    return data


@router.post("/system/dependencies/install")
async def install_system_dependency(
    request: Request,
    body: CliDependencyInstallRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    try:
        data = await ProviderService.install_cli_dependency(body.dependency_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log(
        "OPS",
        "/ops/system/dependencies/install",
        f"{body.dependency_id}:{data.status}",
        operation="EXECUTE",
        actor=_actor_label(auth),
    )
    return data


@router.get("/system/dependencies/install/{dependency_id}/{job_id}")
async def get_system_dependency_install_job(
    request: Request,
    dependency_id: str,
    job_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = ProviderService.get_cli_dependency_install_job(dependency_id, job_id)
    audit_log(
        "OPS",
        f"/ops/system/dependencies/install/{dependency_id}/{job_id}",
        f"{dependency_id}:{job_id}:{data.status}",
        operation="READ",
        actor=_actor_label(auth),
    )
    return data
