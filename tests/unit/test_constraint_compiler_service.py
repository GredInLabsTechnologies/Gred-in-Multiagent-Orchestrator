from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.gimo_server.ops_models import ProviderConfig, ProviderEntry, ProviderRoleBinding, ProviderRolesConfig, TaskConstraints
from tools.gimo_server.services.constraint_compiler_service import ConstraintCompilerService
from tools.gimo_server.services.profile_binding_service import ProfileBindingService
from tools.gimo_server.services.profile_router_service import ProfileRouterService
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.runtime_policy_service import RuntimePolicyService
from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        active="orch-main",
        providers={
            "orch-main": ProviderEntry(type="openai", provider_type="openai", model="gpt-5.4"),
            "worker-1": ProviderEntry(type="openai", provider_type="openai", model="gpt-4o-mini"),
        },
        roles=ProviderRolesConfig(
            orchestrator=ProviderRoleBinding(provider_id="orch-main", model="gpt-5.4"),
            workers=[ProviderRoleBinding(provider_id="worker-1", model="gpt-4o-mini")],
        ),
    )


def _policy_decision(decision: str = "allow", status_code: str = "POLICY_ALLOW") -> SimpleNamespace:
    return SimpleNamespace(
        decision=decision,
        status_code=status_code,
        policy_hash_expected="expected",
        policy_hash_runtime="runtime",
        triggered_rules=[],
    )


def test_constraint_compiler_clamps_workspace_experiment_for_ephemeral_surface(monkeypatch):
    monkeypatch.setattr(ProviderService, "get_config", classmethod(lambda cls: _provider_config()))
    monkeypatch.setattr(
        RuntimePolicyService,
        "evaluate_draft_policy",
        classmethod(lambda cls, **_kwargs: _policy_decision()),
    )

    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t1",
            "title": "Implement fix",
            "description": "Apply the code change and update the module",
        }
    )

    constraints = ConstraintCompilerService.compile_for_descriptor(
        descriptor,
        task_context={
            "surface": "chatgpt_app",
            "workspace_mode": "ephemeral",
        },
    )

    assert constraints.surface == "chatgpt_app"
    assert constraints.workspace_mode == "ephemeral"
    assert constraints.allowed_policies == ["workspace_safe"]
    assert constraints.allowed_bindings[0].provider_id == "worker-1"


def test_constraint_compiler_rejects_workspace_mode_not_allowed_for_surface():
    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t_invalid_mode",
            "title": "Implement fix",
            "description": "Apply the code change and update the module",
        }
    )

    constraints = ConstraintCompilerService.compile_for_descriptor(
        descriptor,
        task_context={
            "surface": "chatgpt_app",
            "workspace_mode": "source_repo",
        },
    )

    assert constraints.allowed_policies == []
    assert constraints.policy_decision == "deny"
    assert constraints.policy_status_code == "WORKSPACE_MODE_NOT_ALLOWED"
    assert constraints.workspace_mode == "source_repo"
    assert "workspace_mode_rejected_for_surface" in constraints.compiler_notes


def test_constraint_compiler_allows_runtime_only_for_allowlisted_tasks(monkeypatch):
    monkeypatch.setattr(ProviderService, "get_config", classmethod(lambda cls: _provider_config()))
    monkeypatch.setattr(
        RuntimePolicyService,
        "evaluate_draft_policy",
        classmethod(lambda cls, **_kwargs: _policy_decision()),
    )

    approval_descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "gate",
            "title": "Ask approval",
            "description": "Human gate before execution",
        }
    )
    allowed = ConstraintCompilerService.compile_for_descriptor(
        approval_descriptor,
        task_context={
            "requested_role": "human_gate",
            "binding_mode": "runtime",
            "depends_on": ["t_prev"],
        },
    )

    planning_descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "orch",
            "title": "Lead orchestrator",
            "description": "Plan the work and coordinate execution",
            "scope": "bridge",
        }
    )
    rejected = ConstraintCompilerService.compile_for_descriptor(
        planning_descriptor,
        task_context={
            "requested_role": "orchestrator",
            "binding_mode": "runtime",
            "depends_on": ["t_prev"],
        },
    )

    assert allowed.allowed_binding_modes[0] == "runtime"
    assert rejected.allowed_binding_modes == ["plan_time"]
    assert "runtime_binding_rejected_by_allowlist" in rejected.compiler_notes


def test_profile_binding_cannot_escape_compiled_envelope():
    constraints = TaskConstraints(
        allowed_policies=["workspace_safe"],
        allowed_binding_modes=["plan_time"],
        allowed_bindings=[ProviderRoleBinding(provider_id="worker-1", model="gpt-4o-mini")],
    )

    binding = ProfileBindingService.resolve_binding(
        requested_provider="orch-main",
        requested_model="gpt-5.4",
        binding_mode="runtime",
        constraints=constraints,
    )

    assert binding.provider == "worker-1"
    assert binding.model == "gpt-4o-mini"
    assert binding.binding_mode == "plan_time"


def test_constraint_compiler_requires_human_approval_for_core_runtime_scope(monkeypatch):
    monkeypatch.setattr(ProviderService, "get_config", classmethod(lambda cls: _provider_config()))
    monkeypatch.setattr(
        RuntimePolicyService,
        "evaluate_draft_policy",
        classmethod(lambda cls, **_kwargs: _policy_decision()),
    )

    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t4",
            "title": "Implement runtime change",
            "description": "Update the runtime policy integration",
            "path_scope": ["tools/gimo_server/services/runtime_policy_service.py"],
        }
    )

    constraints = ConstraintCompilerService.compile_for_descriptor(
        descriptor,
        task_context={"workspace_mode": "source_repo"},
    )

    assert constraints.intent_effective == "CORE_RUNTIME_CHANGE"
    assert constraints.requires_human_approval is True


def test_constraint_compiler_policy_deny_blocks_router(monkeypatch):
    monkeypatch.setattr(ProviderService, "get_config", classmethod(lambda cls: _provider_config()))
    monkeypatch.setattr(
        RuntimePolicyService,
        "evaluate_draft_policy",
        classmethod(lambda cls, **_kwargs: _policy_decision("deny", "DRAFT_REJECTED_FORBIDDEN_SCOPE")),
    )

    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t5",
            "title": "Implement forbidden fix",
            "description": "Apply code changes in a forbidden scope",
            "path_scope": ["tools/gimo_server/security/auth.py"],
        }
    )
    constraints = ConstraintCompilerService.compile_for_descriptor(
        descriptor,
        task_context={"workspace_mode": "source_repo"},
    )

    assert constraints.allowed_policies == []
    with pytest.raises(ValueError, match="no allowed execution policies"):
        ProfileRouterService.route(
            descriptor=descriptor,
            constraints=constraints,
            requested_preset="executor",
        )
