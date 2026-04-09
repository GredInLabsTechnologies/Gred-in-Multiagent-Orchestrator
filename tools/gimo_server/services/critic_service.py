from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .providers.service import ProviderService


class CriticVerdict(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    severity: Literal["none", "minor", "major", "critical"] = "none"


class CriticService:
    """Hidden critic pass for executor outputs with bounded retries."""

    CRITIC_PROMPT = (
        "You are a strict execution critic. Evaluate output quality, safety and actionability. "
        "Return JSON with: approved (bool), issues (string[]), severity (none|minor|major|critical)."
    )

    @classmethod
    async def evaluate(cls, output: str, context: dict[str, Any] | None = None) -> CriticVerdict:
        ctx = dict(context or {})
        prompt = (
            f"{cls.CRITIC_PROMPT}\n\n"
            f"Context: {ctx}\n\n"
            f"Output:\n{output}\n"
        )
        resp = await ProviderService.static_generate(
            prompt,
            context={"task_type": "critic_review", "model": ctx.get("model") or "auto"},
        )
        content = str(resp.get("content") or "").strip()

        import json
        import re

        if content.startswith("```"):
            content = re.sub(r"```\w*\n?", "", content).strip()
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start:end + 1]

        try:
            data = json.loads(content)
            return CriticVerdict.model_validate(data)
        except Exception:
            # Fail-closed: malformed critic payload should not silently approve.
            return CriticVerdict(
                approved=False,
                issues=["critic_payload_parse_failed"],
                severity="major",
            )
