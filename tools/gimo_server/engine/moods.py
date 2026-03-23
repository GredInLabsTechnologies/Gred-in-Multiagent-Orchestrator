"""GIMO Mood Engine — Comprehensive behavioral profiles for agent orchestration.

P2 Innovation: Moods are elevated from a Skills-only feature to the core control
system for the agentic loop. Each mood is a complete operational profile that
determines personality, temperature, tool access, response style, and auto-transitions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal, Set

__all__ = ["MoodType", "MoodProfile", "MOOD_PROFILES", "get_mood_profile", "MOOD_PROMPTS"]

MoodType = Literal["neutral", "forensic", "executor", "dialoger", "creative", "guardian", "mentor"]


@dataclass(frozen=True)
class MoodProfile:
    """Complete behavioral profile for a mood.

    Each mood defines not just the prompt, but the entire agent's operational parameters.
    This enables mood-driven flow control without explicit phase state machines.
    """
    name: str
    prompt_prefix: str              # Injected into system prompt
    temperature: float              # 0.0 = deterministic, 0.7 = exploratory
    max_turns: int                  # Loop iteration limit
    tool_whitelist: Set[str]        # Tools available (empty = all allowed)
    tool_blacklist: Set[str]        # Tools prohibited
    requires_confirmation: Set[str] # Tools that trigger ask_user BEFORE execution
    response_style: str             # "concise" | "detailed" | "educational"
    auto_transition_to: str         # Mood suggested after completion ("stay" = no change)


# ── Mood Profiles ─────────────────────────────────────────────────────────────

MOOD_PROFILES: Dict[str, MoodProfile] = {
    "neutral": MoodProfile(
        name="neutral",
        prompt_prefix="",
        temperature=0.2,
        max_turns=25,
        tool_whitelist=set(),
        tool_blacklist=set(),
        requires_confirmation=set(),
        response_style="concise",
        auto_transition_to="stay",
    ),

    "forensic": MoodProfile(
        name="forensic",
        prompt_prefix=(
            "[MOOD: FORENSIC] You are meticulous and analytical. "
            "Investigate every detail, trace root causes, question assumptions, "
            "and produce exhaustive evidence-backed findings. Never skip edge cases."
        ),
        temperature=0.0,
        max_turns=25,
        tool_whitelist={"read_file", "list_files", "search_text", "ask_user"},
        tool_blacklist=set(),
        requires_confirmation={"write_file", "shell_exec", "patch_file", "search_replace"},
        response_style="detailed",
        auto_transition_to="dialoger",
    ),

    "executor": MoodProfile(
        name="executor",
        prompt_prefix=(
            "[MOOD: EXECUTOR] You are direct and results-oriented. "
            "Cut through ambiguity, make decisions fast, ship working output. "
            "Minimize discussion, maximize throughput."
        ),
        temperature=0.1,
        max_turns=15,
        tool_whitelist=set(),  # All tools available
        tool_blacklist=set(),
        requires_confirmation=set(),
        response_style="concise",
        auto_transition_to="mentor",
    ),

    "dialoger": MoodProfile(
        name="dialoger",
        prompt_prefix=(
            "[MOOD: DIALOGER] You are collaborative and consultative. "
            "Before acting, ask clarifying questions. Propose options to the user. "
            "Seek agreement before executing irreversible actions."
        ),
        temperature=0.3,
        max_turns=25,
        tool_whitelist={"ask_user", "propose_plan", "web_search", "read_file", "list_files", "search_text"},
        tool_blacklist=set(),
        requires_confirmation={"write_file", "shell_exec", "patch_file", "search_replace", "create_dir"},
        response_style="detailed",
        auto_transition_to="forensic",  # After dialog, often need to investigate
    ),

    "creative": MoodProfile(
        name="creative",
        prompt_prefix=(
            "[MOOD: CREATIVE] You are imaginative and exploratory. "
            "Suggest unconventional approaches, explore alternative solutions, "
            "and think outside established patterns. Challenge the status quo."
        ),
        temperature=0.7,
        max_turns=20,
        tool_whitelist=set(),
        tool_blacklist=set(),
        requires_confirmation=set(),
        response_style="detailed",
        auto_transition_to="executor",
    ),

    "guardian": MoodProfile(
        name="guardian",
        prompt_prefix=(
            "[MOOD: GUARDIAN] You are security-focused and cautious. "
            "Prioritize safety, validate inputs, check for vulnerabilities, "
            "and raise warnings about risky operations before proceeding."
        ),
        temperature=0.0,
        max_turns=25,
        tool_whitelist={"read_file", "list_files", "search_text", "shell_exec"},  # shell_exec for validation only
        tool_blacklist=set(),
        requires_confirmation={"write_file", "patch_file", "search_replace", "create_dir"},
        response_style="detailed",
        auto_transition_to="dialoger",
    ),

    "mentor": MoodProfile(
        name="mentor",
        prompt_prefix=(
            "[MOOD: MENTOR] You are educational and explanatory. "
            "Teach as you work. Explain your reasoning, share best practices, "
            "and help the user learn from the process."
        ),
        temperature=0.3,
        max_turns=25,
        tool_whitelist=set(),
        tool_blacklist=set(),
        requires_confirmation=set(),
        response_style="educational",
        auto_transition_to="stay",
    ),
}


# ── Backward Compatibility ────────────────────────────────────────────────────

# Legacy MOOD_PROMPTS dict for skills_service.py (read-only)
MOOD_PROMPTS: Dict[str, str] = {
    name: profile.prompt_prefix
    for name, profile in MOOD_PROFILES.items()
}


# ── API ───────────────────────────────────────────────────────────────────────

def get_mood_profile(mood: str) -> MoodProfile:
    """Get the full MoodProfile for a given mood name.

    Raises KeyError if mood is invalid.
    """
    return MOOD_PROFILES[mood]
