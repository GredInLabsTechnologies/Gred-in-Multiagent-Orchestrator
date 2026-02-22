from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import OPS_DATA_DIR

logger = logging.getLogger("orchestrator.skills")

SKILLS_DIR = OPS_DATA_DIR / "skills"

# ──────────────────────────────────────────────────────────────────────────────
# Pydantic models (kept here to avoid ops_models.py bloat)
# ──────────────────────────────────────────────────────────────────────────────
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class Skill(BaseModel):
    """A reusable plan template (Skill) that can be triggered on-demand."""

    id: str
    name: str
    description: str = ""
    icon: str = "⚡"          # emoji shown in the UI card
    category: str = "general"  # e.g. 'security', 'review', 'deploy'
    prompt_template: str        # the prompt sent to the LLM / OpsService
    tags: List[str] = Field(default_factory=list)
    next_skill_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_run_at: Optional[datetime] = None
    run_count: int = 0


class SkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    icon: str = "⚡"
    category: str = "general"
    prompt_template: str
    tags: List[str] = Field(default_factory=list)
    next_skill_id: Optional[str] = None


class SkillUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    category: Optional[str] = None
    prompt_template: Optional[str] = None
    tags: Optional[List[str]] = None
    next_skill_id: Optional[str] = None


# Service
# ──────────────────────────────────────────────────────────────────────────────

_BUILTINS: List[Dict[str, Any]] = [
    {
        "id": "skill_security_review",
        "name": "Security Audit",
        "description": "Scan the repository for common vulnerabilities and generate a threat report.",
        "icon": "🔒",
        "category": "security",
        "prompt_template": "Perform a thorough security audit of the repository. List all vulnerabilities found by severity (CRITICAL, HIGH, MEDIUM, LOW). For each, provide the file path, line, description, and recommended fix.",
        "tags": ["security", "audit"],
    },
    {
        "id": "skill_test_coverage",
        "name": "Test Coverage Report",
        "description": "Identify functions/modules with no tests and propose new test cases.",
        "icon": "🧪",
        "category": "review",
        "prompt_template": "Analyze the repository and identify all public functions and modules that lack unit tests. For each gap, propose a concrete test case with inputs and expected outputs.",
        "tags": ["testing", "quality"],
    },
    {
        "id": "skill_ci_summary",
        "name": "CI Failure Summary",
        "description": "Summarise the latest CI failures and suggest fixes.",
        "icon": "🚨",
        "category": "review",
        "prompt_template": "Summarise the latest CI/CD pipeline failures in the repository. Group them by root cause, explain each issue, and suggest the minimal code change needed to fix it.",
        "tags": ["ci", "review"],
    },
    {
        "id": "skill_refactor_hints",
        "name": "Refactor Hints",
        "description": "Find files with high complexity and suggest targeted refactors.",
        "icon": "♻️",
        "category": "quality",
        "prompt_template": "Scan the codebase for high-complexity or duplicated code. Identify the top 5 candidates for refactoring, explain why, and provide a concrete refactoring plan for each.",
        "tags": ["refactor", "quality"],
    },
    {
        "id": "skill_doc_gen",
        "name": "Generate Docstrings",
        "description": "Auto-generate missing docstrings for Python/TS functions.",
        "icon": "📝",
        "category": "docs",
        "prompt_template": "Identify all functions and classes in the repository that lack docstrings or JSDoc comments. Generate complete, accurate documentation in the language-appropriate format for each.",
        "tags": ["docs", "quality"],
    },
]


class SkillsService:
    """File-backed service for managing Skill templates."""

    @classmethod
    def _ensure_dir(cls) -> None:
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        # Seed built-in skills if the dir is empty
        if not any(SKILLS_DIR.glob("*.json")):
            for s in _BUILTINS:
                data = json.dumps(s, ensure_ascii=False, default=str)
                (SKILLS_DIR / f"{s['id']}.json").write_text(data, encoding="utf-8")

    @classmethod
    def _skill_path(cls, skill_id: str) -> Path:
        return SKILLS_DIR / f"{skill_id}.json"

    # ── CRUD ──────────────────────────────────────────────────────────────────

    @classmethod
    def list_skills(cls) -> List[Skill]:
        cls._ensure_dir()
        skills: List[Skill] = []
        for f in SKILLS_DIR.glob("*.json"):
            try:
                skills.append(Skill.model_validate_json(f.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.warning("Failed to parse skill %s: %s", f.name, exc)
        return sorted(skills, key=lambda s: s.name)

    @classmethod
    def get_skill(cls, skill_id: str) -> Optional[Skill]:
        cls._ensure_dir()
        p = cls._skill_path(skill_id)
        if not p.exists():
            return None
        return Skill.model_validate_json(p.read_text(encoding="utf-8"))

    @classmethod
    def create_skill(cls, req: SkillCreateRequest) -> Skill:
        cls._ensure_dir()
        skill_id = f"skill_{int(time.time() * 1000)}_{os.urandom(2).hex()}"
        skill = Skill(id=skill_id, **req.model_dump())
        cls._skill_path(skill_id).write_text(
            skill.model_dump_json(indent=2), encoding="utf-8"
        )
        logger.info("Skill created: %s (%s)", skill.name, skill.id)
        return skill

    @classmethod
    def update_skill(cls, skill_id: str, req: SkillUpdateRequest) -> Optional[Skill]:
        skill = cls.get_skill(skill_id)
        if not skill:
            return None
        data = skill.model_dump()
        for field, val in req.model_dump(exclude_none=True).items():
            data[field] = val
        data["updated_at"] = datetime.now(timezone.utc)
        updated = Skill.model_validate(data)
        cls._skill_path(skill_id).write_text(updated.model_dump_json(indent=2), encoding="utf-8")
        return updated

    @classmethod
    def delete_skill(cls, skill_id: str) -> bool:
        p = cls._skill_path(skill_id)
        if p.exists():
            p.unlink()
            logger.info("Skill deleted: %s", skill_id)
            return True
        return False

    # ── Trigger (creates a draft from template) ───────────────────────────────

    @classmethod
    def trigger_skill(cls, skill_id: str, actor: str = "user", context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        Instantiates a Skill as an OpsService draft.
        Returns the draft_id on success, None if skill not found.
        """
        from ..services.ops_service import OpsService

        skill = cls.get_skill(skill_id)
        if not skill:
            return None

        # Resolve placeholders in prompt_template
        prompt = skill.prompt_template
        merged_context = {
            "skill_id": skill_id, 
            "skill_name": skill.name,
            "next_skill_id": skill.next_skill_id
        }
        if context:
            merged_context.update(context)
            try:
                prompt = prompt.format(**merged_context)
            except KeyError as e:
                logger.warning("Missing context key for skill template: %s", e)
            except Exception as e:
                logger.error("Failed to format skill template: %s", e)

        draft = OpsService.create_draft(
            prompt=prompt,
            context=merged_context,
            provider="skills_engine",
            status="draft",
        )

        # Update run stats
        skill.last_run_at = datetime.now(timezone.utc)
        skill.run_count += 1
        cls._skill_path(skill_id).write_text(skill.model_dump_json(indent=2), encoding="utf-8")

        logger.info("Skill '%s' triggered by %s → Draft %s", skill.name, actor, draft.id)
        return draft.id
