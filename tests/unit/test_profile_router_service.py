from __future__ import annotations

import pytest

from tools.gimo_server.ops_models import TaskConstraints
from tools.gimo_server.services.constraint_compiler_service import ConstraintCompilerService
from tools.gimo_server.services.profile_router_service import ProfileRouterService
from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService


def test_profile_router_selects_researcher_for_research_descriptor():
    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t1",
            "title": "Investigate API docs",
            "description": "Research the endpoint and summarize findings",
            "agent_mood": "forensic",
        }
    )
    constraints = ConstraintCompilerService.compile_for_descriptor(descriptor)

    decision = ProfileRouterService.route(descriptor=descriptor, constraints=constraints, legacy_mood="forensic")

    assert decision.resolved_profile.agent_preset == "researcher"
    assert decision.resolved_profile.execution_policy == "docs_research"
    assert decision.resolved_profile.workflow_phase == "planning"


def test_profile_router_selects_executor_for_workspace_mutation():
    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t2",
            "title": "Implement fix",
            "description": "Apply the code change and update the module",
            "agent_preset": "executor",
        }
    )
    constraints = ConstraintCompilerService.compile_for_descriptor(descriptor)

    decision = ProfileRouterService.route(descriptor=descriptor, constraints=constraints, requested_preset="executor")

    assert decision.resolved_profile.agent_preset == "executor"
    assert decision.resolved_profile.execution_policy in {"workspace_safe", "workspace_experiment"}
    assert decision.binding_mode == "plan_time"


def test_profile_router_rejects_requested_mutating_preset_under_read_only_envelope():
    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t_review",
            "title": "Review patch",
            "description": "Review and validate the changes",
        }
    )
    constraints = ConstraintCompilerService.compile_for_descriptor(descriptor)

    decision = ProfileRouterService.route(
        descriptor=descriptor,
        constraints=constraints,
        requested_preset="executor",
    )

    assert decision.resolved_profile.agent_preset == "reviewer"
    assert decision.resolved_profile.task_role == "reviewer"
    assert decision.resolved_profile.execution_policy == "read_only"
    assert decision.candidate_count == 2
    assert "objective=constraints>requested>legacy>semantic>gics_advisory" in decision.routing_reason


def test_profile_router_refuses_to_route_when_constraints_deny_all_policies():
    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t3",
            "title": "Implement fix",
            "description": "Apply the code change and update the module",
        }
    )

    with pytest.raises(ValueError, match="no allowed execution policies"):
        ProfileRouterService.route(
            descriptor=descriptor,
            constraints=TaskConstraints(allowed_policies=[]),
            requested_preset="executor",
        )
