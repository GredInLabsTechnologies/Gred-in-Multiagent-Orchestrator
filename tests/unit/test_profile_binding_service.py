from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.gimo_server.ops_models import ProviderConfig, ProviderEntry, ProviderRoleBinding, ProviderRolesConfig, TaskConstraints
from tools.gimo_server.services.model_inventory_service import ModelEntry, ModelInventoryService
from tools.gimo_server.services.model_router_service import ModelRouterService, RoutingDecision
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.profile_binding_service import ProfileBindingService
from tools.gimo_server.services.providers.service_impl import ProviderService
from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        active="orch-main",
        providers={
            "orch-main": ProviderEntry(
                type="openai",
                provider_type="openai",
                model="gpt-5.4",
                capabilities={"requires_remote_api": True},
            ),
            "wk-local": ProviderEntry(
                type="openai",
                provider_type="openai",
                model="gpt-4o-mini",
                capabilities={"requires_remote_api": False},
            ),
            "wk-remote": ProviderEntry(
                type="openai",
                provider_type="openai",
                model="gpt-4.1-mini",
                capabilities={"requires_remote_api": True},
            ),
        },
        roles=ProviderRolesConfig(
            orchestrator=ProviderRoleBinding(provider_id="orch-main", model="gpt-5.4"),
            workers=[
                ProviderRoleBinding(provider_id="wk-local", model="gpt-4o-mini"),
                ProviderRoleBinding(provider_id="wk-remote", model="gpt-4.1-mini"),
            ],
        ),
    )


def _inventory() -> list[ModelEntry]:
    return [
        ModelEntry(
            model_id="gpt-5.4",
            provider_id="orch-main",
            provider_type="openai",
            is_local=False,
            quality_tier=5,
            size_gb=0.0,
            capabilities={"chat", "reasoning", "code"},
            cost_input=5.0,
            cost_output=15.0,
        ),
        ModelEntry(
            model_id="gpt-4o-mini",
            provider_id="wk-local",
            provider_type="openai",
            is_local=True,
            quality_tier=3,
            size_gb=4.0,
            capabilities={"chat", "code"},
            cost_input=0.2,
            cost_output=0.8,
        ),
        ModelEntry(
            model_id="gpt-4.1-mini",
            provider_id="wk-remote",
            provider_type="openai",
            is_local=False,
            quality_tier=3,
            size_gb=0.0,
            capabilities={"chat", "code"},
            cost_input=0.1,
            cost_output=0.4,
        ),
    ]


def test_profile_binding_prefers_worker_topology_for_code_generation(monkeypatch):
    monkeypatch.setattr(ProviderService, "get_config", classmethod(lambda cls: _provider_config()))
    monkeypatch.setattr(ModelInventoryService, "get_available_models", classmethod(lambda cls: _inventory()))
    monkeypatch.setattr(OpsService, "get_model_reliability", classmethod(lambda cls, **_kwargs: None))

    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t_impl",
            "title": "Implement fix",
            "description": "Apply the code change and update the module",
        }
    )
    constraints = TaskConstraints(
        allowed_policies=["workspace_safe"],
        allowed_binding_modes=["plan_time"],
        allowed_bindings=[
            ProviderRoleBinding(provider_id="orch-main", model="gpt-5.4"),
            ProviderRoleBinding(provider_id="wk-local", model="gpt-4o-mini"),
        ],
    )

    resolution = ProfileBindingService.resolve_binding_decision(descriptor=descriptor, constraints=constraints)

    assert resolution.binding.provider == "wk-local"
    assert resolution.binding.model == "gpt-4o-mini"
    assert "objective=constraints>success>quality>latency>cost" in resolution.reason
    assert "topology_preference=wk-local/gpt-4o-mini" in resolution.reason


def test_profile_binding_fails_closed_when_constraints_allow_no_bindings():
    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t_impl",
            "title": "Implement fix",
            "description": "Apply the code change and update the module",
        }
    )
    constraints = TaskConstraints(
        allowed_policies=["workspace_safe"],
        allowed_binding_modes=["plan_time"],
        allowed_bindings=[],
    )

    with pytest.raises(ValueError, match="no allowed bindings"):
        ProfileBindingService.resolve_binding_decision(descriptor=descriptor, constraints=constraints)


def test_profile_binding_prefers_orchestrator_topology_for_analysis(monkeypatch):
    monkeypatch.setattr(ProviderService, "get_config", classmethod(lambda cls: _provider_config()))
    monkeypatch.setattr(ModelInventoryService, "get_available_models", classmethod(lambda cls: _inventory()))
    monkeypatch.setattr(OpsService, "get_model_reliability", classmethod(lambda cls, **_kwargs: None))

    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t_plan",
            "title": "Lead orchestrator",
            "description": "Plan the work and coordinate execution",
            "scope": "bridge",
        }
    )
    constraints = TaskConstraints(
        allowed_policies=["propose_only"],
        allowed_binding_modes=["plan_time"],
        allowed_bindings=[
            ProviderRoleBinding(provider_id="orch-main", model="gpt-5.4"),
            ProviderRoleBinding(provider_id="wk-local", model="gpt-4o-mini"),
        ],
    )

    resolution = ProfileBindingService.resolve_binding_decision(descriptor=descriptor, constraints=constraints)

    assert resolution.binding.provider == "orch-main"
    assert resolution.binding.model == "gpt-5.4"
    assert "topology_preference=orch-main/gpt-5.4" in resolution.reason


def test_model_router_gics_only_adjusts_score_within_constrained_candidates(monkeypatch):
    monkeypatch.setattr(ProviderService, "get_config", classmethod(lambda cls: _provider_config()))
    monkeypatch.setattr(ModelInventoryService, "get_available_models", classmethod(lambda cls: _inventory()))
    monkeypatch.setattr(ModelRouterService, "resolve_tier_routing", classmethod(lambda cls, task_type, config: (None, None)))

    def _reliability(cls, *, provider_type: str, model_id: str):
        if model_id == "gpt-4.1-mini":
            return {"score": 0.95, "anomaly": False}
        return {"score": 0.40, "anomaly": False}

    monkeypatch.setattr(OpsService, "get_model_reliability", classmethod(_reliability))

    decision = ModelRouterService.choose_binding_from_candidates(
        task_type="execution",
        candidates=[
            ProviderRoleBinding(provider_id="wk-local", model="gpt-4o-mini"),
            ProviderRoleBinding(provider_id="wk-remote", model="gpt-4.1-mini"),
        ],
    )

    assert decision.provider_id == "wk-remote"
    assert decision.model == "gpt-4.1-mini"
    assert "gics_reliability=0.95" in decision.reason


def test_model_router_enforces_required_capability_and_quality_floor(monkeypatch):
    cfg = ProviderConfig(
        active="wk-local",
        providers={
            "wk-local": ProviderEntry(
                type="ollama",
                provider_type="ollama",
                model="tiny-chat",
                capabilities={"requires_remote_api": False},
            ),
            "wk-remote": ProviderEntry(
                type="openai",
                provider_type="openai",
                model="coder-pro",
                capabilities={"requires_remote_api": True},
            ),
        },
        roles=ProviderRolesConfig(
            orchestrator=ProviderRoleBinding(provider_id="wk-local", model="tiny-chat"),
            workers=[
                ProviderRoleBinding(provider_id="wk-local", model="tiny-chat"),
                ProviderRoleBinding(provider_id="wk-remote", model="coder-pro"),
            ],
        ),
    )
    inventory = [
        ModelEntry(
            model_id="tiny-chat",
            provider_id="wk-local",
            provider_type="ollama",
            is_local=True,
            quality_tier=1,
            size_gb=2.0,
            capabilities={"chat"},
            cost_input=0.0,
            cost_output=0.0,
        ),
        ModelEntry(
            model_id="coder-pro",
            provider_id="wk-remote",
            provider_type="openai",
            is_local=False,
            quality_tier=3,
            size_gb=0.0,
            capabilities={"chat", "code"},
            cost_input=0.8,
            cost_output=1.6,
        ),
    ]
    monkeypatch.setattr(ProviderService, "get_config", classmethod(lambda cls: cfg))
    monkeypatch.setattr(ModelInventoryService, "get_available_models", classmethod(lambda cls: inventory))
    monkeypatch.setattr(
        ModelRouterService,
        "resolve_tier_routing",
        classmethod(lambda cls, task_type, config: ("wk-local", "tiny-chat")),
    )
    monkeypatch.setattr(OpsService, "get_model_reliability", classmethod(lambda cls, **_kwargs: None))

    decision = ModelRouterService.choose_binding_from_candidates(
        task_type="code_generation",
        candidates=[
            ProviderRoleBinding(provider_id="wk-local", model="tiny-chat"),
            ProviderRoleBinding(provider_id="wk-remote", model="coder-pro"),
        ],
    )

    assert decision.provider_id == "wk-remote"
    assert decision.model == "coder-pro"
    assert "task=code_generation(cap=code,tier>=3)" in decision.reason
    assert "selected=wk-remote/coder-pro" in decision.reason
    assert "topology_preference=wk-local/tiny-chat" in decision.reason


def test_provider_service_impl_subordinates_auto_binding_to_model_router(monkeypatch):
    monkeypatch.setattr(
        ModelRouterService,
        "choose_binding_from_candidates",
        classmethod(
            lambda cls, **_kwargs: RoutingDecision(
                model="gpt-4o-mini",
                provider_id="wk-local",
                reason="objective=constraints>success>quality>latency>cost|selected=wk-local/gpt-4o-mini",
            )
        ),
    )
    monkeypatch.setattr(
        ProviderService,
        "_select_runtime_binding_with_reliability",
        classmethod(lambda cls, cfg, *, provider_id, model_id: (provider_id, model_id)),
    )

    provider, model = ProviderService._resolve_effective_provider_and_model(
        _provider_config(),
        context={},
        task_type="execution",
    )

    assert provider == "wk-local"
    assert model == "gpt-4o-mini"


def test_provider_service_impl_preserves_explicit_selected_model(monkeypatch):
    def _should_not_route(cls, **_kwargs):
        raise AssertionError("auto-routing should not run for explicit selected_model")

    monkeypatch.setattr(
        ModelRouterService,
        "choose_binding_from_candidates",
        classmethod(_should_not_route),
    )

    # Model gate validates against inventory; provide a matching entry so explicit model passes through
    _entry = ModelEntry(model_id="explicit-model", provider_id="orch-main", provider_type="openai", is_local=False, quality_tier=3)
    monkeypatch.setattr(
        ModelInventoryService,
        "get_available_models",
        classmethod(lambda cls: [_entry]),
    )
    monkeypatch.setattr(
        ModelInventoryService,
        "find_model",
        classmethod(lambda cls, mid: _entry),
    )

    provider, model = ProviderService._resolve_effective_provider_and_model(
        _provider_config(),
        context={"selected_model": "explicit-model"},
        task_type="execution",
    )

    assert provider == "orch-main"
    assert model == "explicit-model"
