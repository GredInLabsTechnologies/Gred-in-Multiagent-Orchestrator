from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request

from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.skills_service import (
    Skill,
    SkillCreateRequest,
    SkillUpdateRequest,
    SkillsService,
)
from .common import _actor_label, _require_role

router = APIRouter()


@router.get("/skills", response_model=List[Skill])
async def list_skills(
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    """List all available skill templates."""
    return SkillsService.list_skills()


@router.get("/skills/{skill_id}", response_model=Skill)
async def get_skill(
    skill_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    """Get a single skill template by ID."""
    skill = SkillsService.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.post("/skills", response_model=Skill, status_code=201)
async def create_skill(
    body: SkillCreateRequest,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    """Create a new skill template."""
    _require_role(auth, "operator")
    skill = SkillsService.create_skill(body)
    audit_log("SKILLS", "/ops/skills", skill.id, operation="CREATE", actor=_actor_label(auth))
    return skill


@router.put("/skills/{skill_id}", response_model=Skill)
async def update_skill(
    skill_id: str,
    body: SkillUpdateRequest,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    """Update an existing skill template."""
    _require_role(auth, "operator")
    skill = SkillsService.update_skill(skill_id, body)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    audit_log("SKILLS", f"/ops/skills/{skill_id}", skill.id, operation="UPDATE", actor=_actor_label(auth))
    return skill


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    """Delete a skill template."""
    _require_role(auth, "admin")
    deleted = SkillsService.delete_skill(skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")
    audit_log("SKILLS", f"/ops/skills/{skill_id}", skill_id, operation="DELETE", actor=_actor_label(auth))


@router.post("/skills/{skill_id}/trigger", status_code=201)
async def trigger_skill(
    request: Request,
    skill_id: str,
    auth: AuthContext = Depends(verify_token),
    rl: None = Depends(check_rate_limit),
):
    """
    Trigger a skill: converts its template into an OpsService draft ready for approval.
    Returns the created draft_id.
    """
    _require_role(auth, "operator")
    draft_id = SkillsService.trigger_skill(skill_id, actor=_actor_label(auth))
    if not draft_id:
        raise HTTPException(status_code=404, detail="Skill not found")
    audit_log("SKILLS", f"/ops/skills/{skill_id}/trigger", draft_id, operation="TRIGGER", actor=_actor_label(auth))
    return {"draft_id": draft_id, "skill_id": skill_id}
