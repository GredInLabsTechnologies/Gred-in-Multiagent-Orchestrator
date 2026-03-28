from __future__ import annotations

from tools.gimo_server.ops_models import RoleProfile

from .agent_catalog_service import AgentCatalogService
from .execution_policy_service import ExecutionPolicyService


def get_role_profile(role_name: str) -> RoleProfile:
    try:
        preset_name = AgentCatalogService.preset_for_role_profile(role_name)
    except KeyError:
        raise PermissionError(f"unknown role profile '{role_name}'")
    policy_name = AgentCatalogService.get_preset(preset_name).execution_policy
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
