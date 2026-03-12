from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import (
    ProviderModelsCatalogResponse,
    ProviderModelInstallRequest,
    ProviderModelInstallResponse,
    ProviderValidateRequest,
    ProviderValidateResponse,
)
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.provider_catalog_service import ProviderCatalogService
from .common import _require_role, _actor_label

router = APIRouter()


@router.get("/connectors/{provider_type}/models", response_model=ProviderModelsCatalogResponse)
async def get_provider_models_catalog(
    request: Request,
    provider_type: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await ProviderCatalogService.get_catalog(provider_type)
    audit_log("OPS", f"/ops/connectors/{provider_type}/models", provider_type, operation="READ", actor=_actor_label(auth))
    return data


@router.get("/provider/models", response_model=ProviderModelsCatalogResponse)
async def get_active_provider_models(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    cfg = ProviderService.get_public_config()
    if not cfg or not cfg.provider_type:
        return ProviderModelsCatalogResponse(
            provider_type="unknown",
            installed_models=[],
            available_models=[],
            recommended_models=[],
            can_install=False,
            install_method="manual",
            auth_modes_supported=[],
            warnings=["No provider active"]
        )
    data = await ProviderCatalogService.get_catalog(cfg.provider_type)
    audit_log("OPS", "/ops/provider/models", cfg.provider_type, operation="READ", actor=_actor_label(auth))
    return data


@router.post("/connectors/{provider_type}/models/install", response_model=ProviderModelInstallResponse)
async def install_provider_model(
    request: Request,
    provider_type: str,
    body: ProviderModelInstallRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    data = await ProviderCatalogService.install_model(provider_type, body.model_id)
    audit_log(
        "OPS",
        f"/ops/connectors/{provider_type}/models/install",
        f"{provider_type}:{body.model_id}:{data.status}",
        operation="EXECUTE",
        actor=_actor_label(auth),
    )
    return data


@router.get("/connectors/{provider_type}/models/install/{job_id}", response_model=ProviderModelInstallResponse)
async def get_provider_model_install_job(
    request: Request,
    provider_type: str,
    job_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = ProviderCatalogService.get_install_job(provider_type, job_id)
    audit_log(
        "OPS",
        f"/ops/connectors/{provider_type}/models/install/{job_id}",
        f"{provider_type}:{job_id}:{data.status}",
        operation="READ",
        actor=_actor_label(auth),
    )
    return data


@router.post("/connectors/{provider_type}/validate", response_model=ProviderValidateResponse)
async def validate_provider_credentials(
    request: Request,
    provider_type: str,
    body: ProviderValidateRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await ProviderCatalogService.validate_credentials(provider_type, body)
    audit_log(
        "OPS",
        f"/ops/connectors/{provider_type}/validate",
        f"{provider_type}:{'ok' if data.valid else 'fail'}",
        operation="READ",
        actor=_actor_label(auth),
    )
    return data
