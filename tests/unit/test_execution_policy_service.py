"""Tests for ExecutionPolicyService — policy resolution and canonicalization."""

import pytest
from tools.gimo_server.services.execution_policy_service import ExecutionPolicyService


def test_get_policy_all_names_valid():
    """All canonical policy names resolve to valid policies."""
    policies = [
        "read_only",
        "docs_research",
        "propose_only",
        "workspace_safe",
        "workspace_experiment",
        "security_audit",
    ]
    for policy_name in policies:
        policy = ExecutionPolicyService.get_policy(policy_name)
        assert policy is not None
        assert policy.name == policy_name


def test_canonical_policy_name_identity():
    """canonical_policy_name is idempotent for canonical names."""
    canonical = ExecutionPolicyService.canonical_policy_name("workspace_safe")
    assert canonical == "workspace_safe"


def test_policy_from_legacy_mood():
    """policy_name_from_legacy_mood maps legacy moods to policies."""
    # forensic → analytical → docs_research
    assert ExecutionPolicyService.policy_name_from_legacy_mood("forensic") == "docs_research"
    # executor → assertive → workspace_safe
    assert ExecutionPolicyService.policy_name_from_legacy_mood("executor") == "workspace_safe"
    # neutral → workspace_safe
    assert ExecutionPolicyService.policy_name_from_legacy_mood("neutral") == "workspace_safe"


def test_resolve_policy_prefers_explicit_over_mood():
    """resolve_policy prefers explicit execution_policy over legacy_mood."""
    policy = ExecutionPolicyService.resolve_policy(
        execution_policy="security_audit",
        legacy_mood="forensic",  # would map to docs_research, but ignored
    )
    assert policy.name == "security_audit"


def test_resolve_policy_fallback_from_mood():
    """resolve_policy falls back to legacy_mood when execution_policy is None."""
    policy = ExecutionPolicyService.resolve_policy(
        execution_policy=None,
        legacy_mood="forensic",
    )
    assert policy.name == "docs_research"


def test_resolve_policy_default_fallback():
    """resolve_policy defaults to workspace_safe when both are None."""
    policy = ExecutionPolicyService.resolve_policy(
        execution_policy=None,
        legacy_mood=None,
    )
    assert policy.name == "workspace_safe"
