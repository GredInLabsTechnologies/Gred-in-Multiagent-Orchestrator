"""Capability Profile API — allows the orchestrator to query per-model-per-task_type profiles.

Endpoints:
    GET /ops/capability-profile/{provider_type}/{model_id}
        → Full ModelProfile (strengths, weaknesses, neutral)

    GET /ops/capability-profile/{provider_type}/{model_id}/recommend?task_type=X
        → Best model for a given task_type (uses historical data from all models)
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from .common import _actor_label, _require_role

router = APIRouter()


@router.get("/capability-profile/{provider_type}/{model_id}")
async def get_capability_profile(
    request: Request,
    provider_type: str,
    model_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
) -> Dict[str, Any]:
    """Return the full capability profile for a model across all observed task types."""
    _require_role(auth, "operator")
    audit_log(
        "OPS", f"/ops/capability-profile/{provider_type}/{model_id}",
        model_id, operation="READ", actor=_actor_label(auth),
    )
    from tools.gimo_server.services.capability_profile_service import CapabilityProfileService
    profile = CapabilityProfileService.get_full_profile(
        provider_type=provider_type, model_id=model_id,
    )

    def _cap_to_dict(cap) -> Dict[str, Any]:
        return {
            "task_type": cap.task_type,
            "samples": cap.samples,
            "successes": cap.successes,
            "failures": cap.failures,
            "success_rate": cap.success_rate,
            "failure_streak": cap.failure_streak,
            "last_failure_reason": cap.last_failure_reason,
            "avg_latency_ms": cap.avg_latency_ms,
            "avg_cost_usd": cap.avg_cost_usd,
            "updated_at": cap.updated_at,
        }

    return {
        "provider_type": profile.provider_type,
        "model_id": profile.model_id,
        "total_samples": profile.total_samples,
        "overall_success_rate": profile.overall_success_rate,
        "strengths": [_cap_to_dict(c) for c in profile.strengths],
        "neutral": [_cap_to_dict(c) for c in profile.neutral],
        "weaknesses": [_cap_to_dict(c) for c in profile.weaknesses],
    }


@router.get("/capability-profile/{provider_type}/{model_id}/recommend")
async def recommend_model_for_task(
    request: Request,
    provider_type: str,
    model_id: str,
    task_type: Annotated[str, Query(description="Task type to find the best model for")],
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
) -> Dict[str, Any]:
    """Return the best model for a given task_type based on historical performance."""
    _require_role(auth, "operator")
    audit_log(
        "OPS", f"/ops/capability-profile/{provider_type}/{model_id}/recommend",
        task_type, operation="READ", actor=_actor_label(auth),
    )
    from tools.gimo_server.services.capability_profile_service import CapabilityProfileService
    result = CapabilityProfileService.recommend_model_for_task(task_type=task_type)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No historical data yet for task_type='{task_type}'. Run some tasks first.",
        )
    return result
