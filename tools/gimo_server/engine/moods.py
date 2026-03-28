"""Behavior-only mood profiles for the conversational and node execution loops."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal

from ..services.agent_catalog_service import AgentCatalogService, LEGACY_MOOD_TO_CANONICAL, MOOD_CATALOG

__all__ = [
    "MoodType",
    "MoodProfile",
    "MOOD_PROFILES",
    "LEGACY_MOOD_ALIASES",
    "get_mood_profile",
    "MOOD_PROMPTS",
]

MoodType = Literal[
    "neutral",
    "assertive",
    "calm",
    "analytical",
    "exploratory",
    "cautious",
    "collaborative",
    "didactic",
    "forensic",
    "executor",
    "dialoger",
    "creative",
    "guardian",
    "mentor",
]


@dataclass(frozen=True)
class MoodProfile:
    name: str
    prompt_prefix: str
    temperature: float
    max_turns: int
    response_style: str


MOOD_PROFILES: Dict[str, MoodProfile] = {
    name: MoodProfile(
        name=profile.name,
        prompt_prefix=profile.prompt_prefix,
        temperature=profile.temperature,
        max_turns=profile.max_turns,
        response_style=profile.response_style,
    )
    for name, profile in MOOD_CATALOG.items()
}

LEGACY_MOOD_ALIASES: Dict[str, str] = dict(LEGACY_MOOD_TO_CANONICAL)

MOOD_PROMPTS: Dict[str, str] = {
    **{name: profile.prompt_prefix for name, profile in MOOD_PROFILES.items()},
    **{
        alias: MOOD_PROFILES[canonical].prompt_prefix
        for alias, canonical in LEGACY_MOOD_ALIASES.items()
        if canonical in MOOD_PROFILES
    },
}


def get_mood_profile(mood: str) -> MoodProfile:
    canonical = LEGACY_MOOD_ALIASES.get(mood, mood)
    return MoodProfile(
        name=AgentCatalogService.get_mood(mood).name,
        prompt_prefix=MOOD_PROFILES[canonical].prompt_prefix,
        temperature=MOOD_PROFILES[canonical].temperature,
        max_turns=MOOD_PROFILES[canonical].max_turns,
        response_style=MOOD_PROFILES[canonical].response_style,
    )
