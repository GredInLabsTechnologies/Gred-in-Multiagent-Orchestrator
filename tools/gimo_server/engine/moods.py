"""GIMO mood engine and policy-enforcement contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Literal, Set

__all__ = [
    "MoodType",
    "MoodContract",
    "MoodProfile",
    "MOOD_PROFILES",
    "get_mood_profile",
    "MOOD_PROMPTS",
]

MoodType = Literal["neutral", "forensic", "executor", "dialoger", "creative", "guardian", "mentor"]

_DOC_ALLOWLIST = frozenset({
    "developer.mozilla.org",
    "docs.anthropic.com",
    "docs.github.com",
    "docs.pydantic.dev",
    "docs.python.org",
    "fastapi.tiangolo.com",
    "platform.openai.com",
})


@dataclass(frozen=True)
class MoodContract:
    fs_mode: Literal["read_only", "workspace_only"]
    network_mode: Literal["blocked", "allowlist"]
    allowed_domains: FrozenSet[str] = field(default_factory=frozenset)
    shell_command_patterns: FrozenSet[str] = field(default_factory=frozenset)
    max_cost_per_turn_usd: float = 0.2
    auto_test_on_write: bool = False
    auto_lint_on_write: bool = False


@dataclass(frozen=True)
class MoodProfile:
    """Complete behavioral profile for a mood."""

    name: str
    prompt_prefix: str
    temperature: float
    max_turns: int
    tool_whitelist: Set[str]
    tool_blacklist: Set[str]
    requires_confirmation: Set[str]
    response_style: str
    auto_transition_to: str
    contract: MoodContract


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
        contract=MoodContract(
            fs_mode="workspace_only",
            network_mode="blocked",
            shell_command_patterns=frozenset({r".*"}),
            max_cost_per_turn_usd=0.20,
        ),
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
        tool_whitelist={"read_file", "list_files", "search_text", "ask_user", "web_search"},
        tool_blacklist=set(),
        requires_confirmation={"write_file", "shell_exec", "patch_file", "search_replace"},
        response_style="detailed",
        auto_transition_to="dialoger",
        contract=MoodContract(
            fs_mode="read_only",
            network_mode="allowlist",
            allowed_domains=_DOC_ALLOWLIST,
            shell_command_patterns=frozenset({
                r"^cat\b.*",
                r"^find\b.*",
                r"^git\s+log\b.*",
                r"^grep\b.*",
                r"^rg\b.*",
                r"^wc\b.*",
            }),
            max_cost_per_turn_usd=0.10,
        ),
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
        tool_whitelist=set(),
        tool_blacklist=set(),
        requires_confirmation=set(),
        response_style="concise",
        auto_transition_to="mentor",
        contract=MoodContract(
            fs_mode="workspace_only",
            network_mode="blocked",
            shell_command_patterns=frozenset({r".*"}),
            max_cost_per_turn_usd=0.50,
            auto_test_on_write=True,
            auto_lint_on_write=True,
        ),
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
        auto_transition_to="forensic",
        contract=MoodContract(
            fs_mode="read_only",
            network_mode="allowlist",
            allowed_domains=_DOC_ALLOWLIST,
            shell_command_patterns=frozenset({
                r"^find\b.*",
                r"^grep\b.*",
                r"^rg\b.*",
            }),
            max_cost_per_turn_usd=0.05,
        ),
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
        contract=MoodContract(
            fs_mode="workspace_only",
            network_mode="allowlist",
            allowed_domains=_DOC_ALLOWLIST,
            shell_command_patterns=frozenset({r".*"}),
            max_cost_per_turn_usd=0.30,
        ),
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
        tool_whitelist={"read_file", "list_files", "search_text", "shell_exec"},
        tool_blacklist=set(),
        requires_confirmation={"write_file", "patch_file", "search_replace", "create_dir"},
        response_style="detailed",
        auto_transition_to="dialoger",
        contract=MoodContract(
            fs_mode="read_only",
            network_mode="blocked",
            shell_command_patterns=frozenset({
                r"^bandit\b.*",
                r"^git\s+diff\b.*",
                r"^ruff\b.*",
                r"^semgrep\b.*",
            }),
            max_cost_per_turn_usd=0.05,
        ),
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
        contract=MoodContract(
            fs_mode="read_only",
            network_mode="blocked",
            shell_command_patterns=frozenset({
                r"^cat\b.*",
                r"^find\b.*",
                r"^grep\b.*",
                r"^rg\b.*",
            }),
            max_cost_per_turn_usd=0.10,
        ),
    ),
}

MOOD_PROMPTS: Dict[str, str] = {
    name: profile.prompt_prefix
    for name, profile in MOOD_PROFILES.items()
}


def get_mood_profile(mood: str) -> MoodProfile:
    return MOOD_PROFILES[mood]
