from __future__ import annotations
from typing import Annotated, Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import (
    ProviderModelsCatalogResponse,
    ProviderModelInstallRequest,
    ProviderModelInstallResponse,
    ProviderValidateRequest,
    ProviderValidateResponse,
)
from tools.gimo_server.services.providers.service import ProviderService
from tools.gimo_server.services.providers.catalog_service import ProviderCatalogService
from .common import _require_role, _actor_label

router = APIRouter()


@router.get("/connectors/{provider_type}/models", response_model=ProviderModelsCatalogResponse)
async def get_provider_models_catalog(
    request: Request,
    provider_type: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await ProviderCatalogService.get_catalog(provider_type)
    audit_log("OPS", f"/ops/connectors/{provider_type}/models", provider_type, operation="READ", actor=_actor_label(auth))
    return data


@router.get("/provider/models", response_model=ProviderModelsCatalogResponse)
async def get_active_provider_models(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
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
    _rl: Annotated[None, Depends(check_rate_limit)],
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
    _rl: Annotated[None, Depends(check_rate_limit)],
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


@router.get("/models/benchmarks")
async def get_model_benchmarks(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
    model_id: Optional[str] = Query(None, description="Filter to a specific model"),
    dimension: Optional[str] = Query(None, description="Filter to a specific capability dimension"),
    top_n: int = Query(5, ge=1, le=20, description="Number of top strengths to return per model"),
):
    """Query external benchmark capability profiles for models.

    Returns enriched profiles from LMArena + Open LLM Leaderboard,
    merged and cached. These feed into GICS as priors for the trust engine.
    """
    _require_role(auth, "operator")
    from tools.gimo_server.services import benchmark_enrichment_service as bes

    profiles = await bes.refresh_benchmarks()
    if not profiles:
        return {"models": [], "total": 0, "sources": ["lmarena", "openllm"], "cached": False}

    if model_id:
        profile = bes.lookup_model(model_id, profiles)
        if not profile:
            return {"models": [], "total": 0, "query": model_id}
        strengths = bes.get_model_strengths(model_id, profiles, top_n=top_n)
        return {
            "models": [{
                "model_id": profile.model_id,
                "dimensions": profile.dimensions,
                "sources": profile.sources,
                "params_b": profile.params_b,
                "top_strengths": strengths,
            }],
            "total": 1,
            "query": model_id,
        }

    if dimension:
        # Find best models for this dimension
        ranked = [
            (p.model_id, p.dimensions.get(dimension, 0), p.sources.get(dimension, ""))
            for p in profiles.values()
            if dimension in p.dimensions
        ]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return {
            "dimension": dimension,
            "models": [
                {"model_id": mid, "score": round(score, 3), "source": src}
                for mid, score, src in ranked[:50]
            ],
            "total": len(ranked),
        }

    # Summary: count of profiled models and available dimensions
    all_dims: Dict[str, int] = {}
    for p in profiles.values():
        for d in p.dimensions:
            all_dims[d] = all_dims.get(d, 0) + 1
    return {
        "total_models": len(profiles),
        "dimensions": all_dims,
        "sources": ["lmarena", "openllm"],
    }


@router.post("/connectors/{provider_type}/validate", response_model=ProviderValidateResponse)
async def validate_provider_credentials(
    request: Request,
    provider_type: str,
    body: ProviderValidateRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
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
