from __future__ import annotations

from tools.gimo_server.ops_models import RoleProfile

from .execution_policy_service import ExecutionPolicyService


ROLE_TO_POLICY = {
    "explorer": "docs_research",
    "auditor": "security_audit",
    "executor": "workspace_safe",
}


def get_role_profile(role_name: str) -> RoleProfile:
    policy_name = ROLE_TO_POLICY.get(role_name)
    if policy_name is None:
        raise PermissionError(f"unknown role profile '{role_name}'")
    policy = ExecutionPolicyService.get_policy(policy_name)
    return RoleProfile(
        tools_allowed=set(policy.allowed_tools),
        capability=policy.name,
        trust_tier="t1" if policy.fs_mode == "read_only" else "t2",
        hitl_required=bool(policy.requires_confirmation),
    )


def assert_tool_allowed(role_name: str, tool: str) -> None:
    profile = get_role_profile(role_name)
    if profile.tools_allowed and tool not in profile.tools_allowed:
        raise PermissionError(f"tool '{tool}' not allowed for role profile '{role_name}'")
