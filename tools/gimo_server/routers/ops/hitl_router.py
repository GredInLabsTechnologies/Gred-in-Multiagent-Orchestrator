"""HITL (Human-in-the-Loop) action draft approval endpoints."""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.hitl_gate_service import HitlGateService
from .common import _require_role

logger = logging.getLogger("orchestrator.routers.hitl")

router = APIRouter(tags=["hitl"])


class BatchApproveRequest(BaseModel):
    draft_ids: list[str]


class ReasonBody(BaseModel):
    reason: Optional[str] = None


@router.get("/action-drafts")
async def list_action_drafts(
    auth: Annotated[AuthContext, Depends(verify_token)],
    status: Optional[str] = None,
):
    """List action drafts, optionally filtered by status."""
    return [d.model_dump(mode="json") for d in HitlGateService.list_drafts(status=status)]


@router.get("/action-drafts/{draft_id}")
async def get_action_draft(
    draft_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    draft = HitlGateService.get_draft(draft_id)
    if not draft:
        raise HTTPException(404, "Action draft not found")
    return draft.model_dump(mode="json")


@router.post("/action-drafts/{draft_id}/approve")
async def approve_action_draft(
    draft_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    body: Optional[ReasonBody] = None,
):
    _require_role(auth, "operator")
    try:
        draft = await HitlGateService.approve(
            draft_id, reason=body.reason if body else None,
        )
        return draft.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.post("/action-drafts/{draft_id}/reject")
async def reject_action_draft(
    draft_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    body: Optional[ReasonBody] = None,
):
    try:
        draft = await HitlGateService.reject(
            draft_id, reason=body.reason if body else None,
        )
        return draft.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.post("/action-drafts/batch-approve")
async def batch_approve(
    body: BatchApproveRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    _require_role(auth, "operator")
    results = []
    for did in body.draft_ids:
        try:
            d = await HitlGateService.approve(did)
            results.append(d.model_dump(mode="json"))
        except Exception:
            continue
    return results


@router.get("/realtime/metrics")
async def realtime_metrics(
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    """Return notification service delivery metrics."""
    from tools.gimo_server.services.notification_service import NotificationService
    return NotificationService.get_metrics()
