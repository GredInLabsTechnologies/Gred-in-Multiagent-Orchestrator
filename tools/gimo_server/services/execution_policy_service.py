from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Literal

from ..models.agent_routing import ExecutionPolicyName

_DOC_ALLOWLIST = frozenset(
    {
        "developer.mozilla.org",
        "docs.anthropic.com",
        "docs.github.com",
        "docs.pydantic.dev",
        "docs.python.org",
        "fastapi.tiangolo.com",
        "platform.openai.com",
    }
)


@dataclass(frozen=True)
class ExecutionPolicyProfile:
    name: ExecutionPolicyName
    fs_mode: Literal["read_only", "workspace_only"]
    network_mode: Literal["blocked", "allowlist"]
    allowed_domains: FrozenSet[str] = field(default_factory=frozenset)
    allowed_tools: FrozenSet[str] = field(default_factory=frozenset)
    requires_confirmation: FrozenSet[str] = field(default_factory=frozenset)
    shell_command_patterns: FrozenSet[str] = field(default_factory=frozenset)
    max_cost_per_turn_usd: float = 0.2
    auto_test_on_write: bool = False
    auto_lint_on_write: bool = False


EXECUTION_POLICIES: Dict[ExecutionPolicyName, ExecutionPolicyProfile] = {
    "read_only": ExecutionPolicyProfile(
        name="read_only",
        fs_mode="read_only",
        network_mode="blocked",
        allowed_tools=frozenset({"read_file", "list_files", "search_text", "ask_user", "propose_plan", "request_context"}),
        shell_command_patterns=frozenset({r"^cat\b.*", r"^find\b.*", r"^grep\b.*", r"^rg\b.*", r"^wc\b.*"}),
        max_cost_per_turn_usd=0.10,
    ),
    "docs_research": ExecutionPolicyProfile(
        name="docs_research",
        fs_mode="read_only",
        network_mode="allowlist",
        allowed_domains=_DOC_ALLOWLIST,
        allowed_tools=frozenset({"read_file", "list_files", "search_text", "ask_user", "propose_plan", "request_context", "web_search"}),
        requires_confirmation=frozenset({"shell_exec"}),
        shell_command_patterns=frozenset({r"^cat\b.*", r"^find\b.*", r"^git\s+log\b.*", r"^grep\b.*", r"^rg\b.*", r"^wc\b.*"}),
        max_cost_per_turn_usd=0.10,
    ),
    "propose_only": ExecutionPolicyProfile(
        name="propose_only",
        fs_mode="read_only",
        network_mode="allowlist",
        allowed_domains=_DOC_ALLOWLIST,
        allowed_tools=frozenset({"read_file", "list_files", "search_text", "ask_user", "propose_plan", "request_context", "web_search"}),
        requires_confirmation=frozenset({"write_file", "patch_file", "search_replace", "create_dir", "shell_exec"}),
        shell_command_patterns=frozenset({r"^find\b.*", r"^grep\b.*", r"^rg\b.*"}),
        max_cost_per_turn_usd=0.05,
    ),
    "workspace_safe": ExecutionPolicyProfile(
        name="workspace_safe",
        fs_mode="workspace_only",
        network_mode="blocked",
        shell_command_patterns=frozenset({r".*"}),
        max_cost_per_turn_usd=0.50,
        auto_test_on_write=True,
        auto_lint_on_write=True,
    ),
    "workspace_experiment": ExecutionPolicyProfile(
        name="workspace_experiment",
        fs_mode="workspace_only",
        network_mode="allowlist",
        allowed_domains=_DOC_ALLOWLIST,
        shell_command_patterns=frozenset({r".*"}),
        max_cost_per_turn_usd=0.30,
    ),
    "security_audit": ExecutionPolicyProfile(
        name="security_audit",
        fs_mode="read_only",
        network_mode="blocked",
        allowed_tools=frozenset({"read_file", "list_files", "search_text", "shell_exec", "ask_user", "propose_plan", "request_context"}),
        requires_confirmation=frozenset({"write_file", "patch_file", "search_replace", "create_dir"}),
        shell_command_patterns=frozenset({r"^bandit\b.*", r"^git\s+diff\b.*", r"^ruff\b.*", r"^semgrep\b.*"}),
        max_cost_per_turn_usd=0.05,
    ),
}

LEGACY_MOOD_TO_POLICY: Dict[str, ExecutionPolicyName] = {
    "neutral": "workspace_safe",
    "forensic": "docs_research",
    "executor": "workspace_safe",
    "dialoger": "propose_only",
    "creative": "workspace_experiment",
    "guardian": "security_audit",
    "mentor": "read_only",
}


class ExecutionPolicyService:
    @classmethod
    def get_policy(cls, policy_name: str) -> ExecutionPolicyProfile:
        if policy_name not in EXECUTION_POLICIES:
            raise KeyError(policy_name)
        return EXECUTION_POLICIES[policy_name]  # type: ignore[index]

    @classmethod
    def resolve_policy_name(cls, *, execution_policy: str | None = None, legacy_mood: str | None = None) -> ExecutionPolicyName:
        if execution_policy:
            return cls.get_policy(execution_policy).name
        return LEGACY_MOOD_TO_POLICY.get(legacy_mood or "neutral", "workspace_safe")

    @classmethod
    def resolve_policy(cls, *, execution_policy: str | None = None, legacy_mood: str | None = None) -> ExecutionPolicyProfile:
        return cls.get_policy(cls.resolve_policy_name(execution_policy=execution_policy, legacy_mood=legacy_mood))
