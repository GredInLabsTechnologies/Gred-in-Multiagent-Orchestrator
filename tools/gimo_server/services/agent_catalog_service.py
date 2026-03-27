from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet

from ..models.agent_routing import (
    AgentPresetName,
    ExecutionPolicyName,
    MoodName,
    ResolvedAgentProfile,
    TaskRole,
    WorkflowPhase,
)


@dataclass(frozen=True)
class CatalogMoodProfile:
    name: MoodName
    prompt_prefix: str
    temperature: float
    max_turns: int
    response_style: str


@dataclass(frozen=True)
class AgentPresetProfile:
    name: AgentPresetName
    task_role: TaskRole
    mood: MoodName
    execution_policy: ExecutionPolicyName
    workflow_phase: WorkflowPhase


MOOD_CATALOG: Dict[MoodName, CatalogMoodProfile] = {
    "neutral": CatalogMoodProfile("neutral", "", 0.2, 25, "concise"),
    "assertive": CatalogMoodProfile(
        "assertive",
        "[MOOD: ASSERTIVE] You are direct, decisive, and delivery-oriented.",
        0.1,
        15,
        "concise",
    ),
    "calm": CatalogMoodProfile(
        "calm",
        "[MOOD: CALM] You are composed, measured, and steady under ambiguity.",
        0.2,
        20,
        "concise",
    ),
    "analytical": CatalogMoodProfile(
        "analytical",
        "[MOOD: ANALYTICAL] You investigate carefully, trace evidence, and explain findings precisely.",
        0.0,
        25,
        "detailed",
    ),
    "exploratory": CatalogMoodProfile(
        "exploratory",
        "[MOOD: EXPLORATORY] You explore alternatives, surface options, and challenge defaults.",
        0.6,
        20,
        "detailed",
    ),
    "cautious": CatalogMoodProfile(
        "cautious",
        "[MOOD: CAUTIOUS] You prioritize safety, verify assumptions, and avoid risky leaps.",
        0.0,
        25,
        "detailed",
    ),
    "collaborative": CatalogMoodProfile(
        "collaborative",
        "[MOOD: COLLABORATIVE] You work consultatively, clarify uncertainty, and present tradeoffs clearly.",
        0.3,
        25,
        "detailed",
    ),
    "didactic": CatalogMoodProfile(
        "didactic",
        "[MOOD: DIDACTIC] You explain reasoning clearly and teach while solving the task.",
        0.3,
        25,
        "educational",
    ),
}

PRESET_CATALOG: Dict[AgentPresetName, AgentPresetProfile] = {
    "plan_orchestrator": AgentPresetProfile("plan_orchestrator", "orchestrator", "collaborative", "propose_only", "planning"),
    "researcher": AgentPresetProfile("researcher", "researcher", "analytical", "docs_research", "planning"),
    "executor": AgentPresetProfile("executor", "executor", "assertive", "workspace_safe", "executing"),
    "reviewer": AgentPresetProfile("reviewer", "reviewer", "didactic", "read_only", "reviewing"),
    "safety_reviewer": AgentPresetProfile("safety_reviewer", "reviewer", "cautious", "security_audit", "reviewing"),
    "human_gate": AgentPresetProfile("human_gate", "human_gate", "calm", "propose_only", "awaiting_approval"),
}

LEGACY_MOOD_TO_PRESET: Dict[str, AgentPresetName] = {
    "neutral": "plan_orchestrator",
    "forensic": "researcher",
    "executor": "executor",
    "dialoger": "plan_orchestrator",
    "creative": "researcher",
    "guardian": "safety_reviewer",
    "mentor": "reviewer",
}

LEGACY_MOOD_TO_CANONICAL: Dict[str, MoodName] = {
    "neutral": "neutral",
    "forensic": "analytical",
    "executor": "assertive",
    "dialoger": "collaborative",
    "creative": "exploratory",
    "guardian": "cautious",
    "mentor": "didactic",
}

CANONICAL_MOOD_NAMES: FrozenSet[str] = frozenset(MOOD_CATALOG.keys())
LEGACY_MOOD_NAMES: FrozenSet[str] = frozenset(LEGACY_MOOD_TO_PRESET.keys())


class AgentCatalogService:
    @classmethod
    def get_mood(cls, mood: str) -> CatalogMoodProfile:
        canonical = LEGACY_MOOD_TO_CANONICAL.get(mood, mood)
        if canonical not in MOOD_CATALOG:
            raise KeyError(canonical)
        return MOOD_CATALOG[canonical]

    @classmethod
    def get_preset(cls, preset: str) -> AgentPresetProfile:
        if preset not in PRESET_CATALOG:
            raise KeyError(preset)
        return PRESET_CATALOG[preset]  # type: ignore[index]

    @classmethod
    def preset_for_legacy_mood(cls, mood: str) -> AgentPresetName:
        preset = LEGACY_MOOD_TO_PRESET.get(mood)
        if not preset:
            raise KeyError(mood)
        return preset

    @classmethod
    def resolve_profile(
        cls,
        *,
        agent_preset: str | None = None,
        legacy_mood: str | None = None,
        workflow_phase: WorkflowPhase | None = None,
    ) -> ResolvedAgentProfile:
        preset_name = agent_preset or cls.preset_for_legacy_mood(legacy_mood or "neutral")
        preset = cls.get_preset(preset_name)
        return ResolvedAgentProfile(
            agent_preset=preset.name,
            task_role=preset.task_role,
            mood=cls.get_mood(legacy_mood).name if legacy_mood else preset.mood,
            execution_policy=preset.execution_policy,
            workflow_phase=workflow_phase or preset.workflow_phase,
        )
