"""DEPRECATED: This module is deprecated. Use ExecutionPolicyService directly.

Legacy role_profiles.py provided a shim between role names and execution policies.
The canonical approach is to use:
- AgentCatalogService.resolve_profile() to get agent profile
- ExecutionPolicyService.get_policy() to get execution policy
- policy.assert_tool_allowed(tool) to check permissions

This module is kept for backward compatibility only.
"""
from __future__ import annotations

import warnings

from tools.gimo_server.ops_models import RoleProfile

from .agent_catalog_service import AgentCatalogService
from .execution_policy_service import ExecutionPolicyService

warnings.warn(
    "role_profiles.py is deprecated. Use ExecutionPolicyService directly.",
    DeprecationWarning,
    stacklevel=2,
)


def get_role_profile(role_name: str) -> RoleProfile:
    """DEPRECATED: Use ExecutionPolicyService.get_policy() instead."""
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
    """DEPRECATED: Use ExecutionPolicyService.get_policy(policy_name).assert_tool_allowed(tool) instead."""
    profile = get_role_profile(role_name)
    if profile.tools_allowed and tool not in profile.tools_allowed:
        raise PermissionError(f"tool '{tool}' not allowed for role profile '{role_name}'")
