from __future__ import annotations

from typing import Dict, List, Annotated
from fastapi import APIRouter, Depends, HTTPException

from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.skills_service import (
    DuplicateCommandError,
    SkillAnalytics,
    SkillAutoGenRequest,
    SkillDefinition,
    SkillCreateRequest,
    SkillDescriptionRequest,
    SkillExecuteRequest,
    SkillExecuteResponse,
    SkillUpdateRequest,
    SkillsService,
)
from .common import _actor_label, _require_role

router = APIRouter()

_SKILL_NOT_FOUND = "Skill not found"


# ── CRUD ──────────────────────────────────────────────────────────────────────


@router.get("/skills", response_model=List[SkillDefinition])
async def list_skills(
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """List all available skill templates."""
    return SkillsService.list_skills()


@router.get(
    "/skills/{skill_id}",
    response_model=SkillDefinition,
    responses={404: {"description": _SKILL_NOT_FOUND}},
)
async def get_skill(
    skill_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Get a single skill template by ID."""
    skill = SkillsService.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=_SKILL_NOT_FOUND)
    return skill


@router.post(
    "/skills",
    response_model=SkillDefinition,
    status_code=201,
    responses={
        400: {"description": "Invalid visual graph definition"},
        409: {"description": "Skill command already exists"},
    },
)
async def create_skill(
    body: SkillCreateRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Create a new skill template."""
    _require_role(auth, "operator")
    try:
        skill = SkillsService.create_skill(body)
    except DuplicateCommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_log("SKILLS", "/ops/skills", skill.id, operation="CREATE", actor=_actor_label(auth))
    return skill


@router.put(
    "/skills/{skill_id}",
    response_model=SkillDefinition,
    responses={
        400: {"description": "Invalid update data"},
        404: {"description": _SKILL_NOT_FOUND},
    },
)
async def update_skill(
    skill_id: str,
    body: SkillUpdateRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Update a skill, creating a new version (previous version is archived)."""
    _require_role(auth, "operator")
    try:
        updated = SkillsService.update_skill(skill_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail=_SKILL_NOT_FOUND)
    audit_log("SKILLS", f"/ops/skills/{skill_id}", skill_id, operation="UPDATE", actor=_actor_label(auth))
    return updated


@router.delete(
    "/skills/{skill_id}",
    status_code=204,
    responses={404: {"description": _SKILL_NOT_FOUND}},
)
async def delete_skill(
    skill_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Delete a skill template."""
    _require_role(auth, "admin")
    deleted = SkillsService.delete_skill(skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=_SKILL_NOT_FOUND)
    audit_log("SKILLS", f"/ops/skills/{skill_id}", skill_id, operation="DELETE", actor=_actor_label(auth))


# ── Generation ────────────────────────────────────────────────────────────────


@router.post("/skills/generate-description")
async def generate_description(
    body: SkillDescriptionRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Generate a baseline description for a visual Skill payload."""
    _require_role(auth, "operator")
    description = SkillsService.generate_description(body)
    return {"description": description}


@router.post(
    "/skills/generate-from-prompt",
    response_model=SkillDefinition,
    status_code=201,
    responses={
        400: {"description": "Invalid prompt or LLM generation failed"},
        409: {"description": "Generated command already exists"},
    },
)
async def generate_skill_from_prompt(
    body: SkillAutoGenRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Auto-generate a complete skill from a natural language description."""
    _require_role(auth, "operator")
    try:
        skill = await SkillsService.generate_skill_from_prompt(body)
    except DuplicateCommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Generation failed: {exc}") from exc
    audit_log("SKILLS", "/ops/skills/generate-from-prompt", skill.id, operation="AUTO_GEN", actor=_actor_label(auth))
    return skill


# ── Execution ─────────────────────────────────────────────────────────────────


@router.post(
    "/skills/{skill_id}/execute",
    response_model=SkillExecuteResponse,
    status_code=201,
    responses={
        404: {"description": _SKILL_NOT_FOUND},
        500: {"description": "Execution error"},
    },
)
async def execute_skill(
    skill_id: str,
    body: SkillExecuteRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Execute a skill."""
    _require_role(auth, "operator")
    try:
        response = await SkillsService.execute_skill(skill_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    audit_log("SKILLS", f"/ops/skills/{skill_id}/execute", response.skill_run_id, operation="EXECUTE", actor=_actor_label(auth))
    return response


# ── Versioning ────────────────────────────────────────────────────────────────


@router.get("/skills/{skill_id}/versions", response_model=List[SkillDefinition])
async def list_skill_versions(
    skill_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """List all archived versions of a skill."""
    return SkillsService.list_skill_versions(skill_id)


# ── Analytics ─────────────────────────────────────────────────────────────────


@router.get("/skills/{skill_id}/analytics", response_model=SkillAnalytics)
async def get_skill_analytics(
    skill_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Get execution analytics for a skill."""
    return SkillsService.get_skill_analytics(skill_id)


# ── Marketplace ───────────────────────────────────────────────────────────────


@router.get("/skills/marketplace", response_model=List[SkillDefinition])
async def list_marketplace(
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """List all published skills in the marketplace."""
    return SkillsService.list_published_skills()


@router.post(
    "/skills/{skill_id}/publish",
    response_model=SkillDefinition,
    responses={404: {"description": _SKILL_NOT_FOUND}},
)
async def publish_skill(
    skill_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Publish a skill to the marketplace."""
    _require_role(auth, "admin")
    try:
        skill = SkillsService.publish_skill(skill_id, author=_actor_label(auth))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit_log("SKILLS", f"/ops/skills/{skill_id}/publish", skill_id, operation="PUBLISH", actor=_actor_label(auth))
    return skill


@router.post(
    "/skills/marketplace/{skill_id}/install",
    response_model=SkillDefinition,
    status_code=201,
    responses={
        404: {"description": "Marketplace skill not found"},
        409: {"description": "Command already exists locally"},
    },
)
async def install_from_marketplace(
    skill_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Install a skill from the marketplace into local skills."""
    _require_role(auth, "operator")
    try:
        skill = SkillsService.install_from_marketplace(skill_id)
    except DuplicateCommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit_log("SKILLS", f"/ops/skills/marketplace/{skill_id}/install", skill.id, operation="INSTALL", actor=_actor_label(auth))
    return skill


# ── Moods ─────────────────────────────────────────────────────────────────────


@router.get("/skills/moods", response_model=Dict[str, str])
async def list_moods(
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """List all available agent moods with their system prompt descriptions."""
    return SkillsService.list_available_moods()
