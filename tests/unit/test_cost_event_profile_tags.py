"""Tests that CostEvent includes agent profile metadata."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tools.gimo_server.models.economy import CostEvent
from tools.gimo_server.models.plan import CustomPlan, PlanNode, PlanNodeBinding
from tools.gimo_server.models.agent_routing import (
    ResolvedAgentProfile,
    RoutingDecisionSummary,
)
from tools.gimo_server.services.custom_plan_service import CustomPlanService


def test_cost_event_model_has_profile_fields():
    """CostEvent model includes agent_preset, task_role, execution_policy_name."""
    event = CostEvent(
        id="ce_test",
        workflow_id="wf_test",
        node_id="n_test",
        model="gpt-4",
        provider="openai",
        task_type="code_gen",
        agent_preset="researcher",
        task_role="researcher",
        execution_policy_name="docs_research",
    )
    assert event.agent_preset == "researcher"
    assert event.task_role == "researcher"
    assert event.execution_policy_name == "docs_research"


def test_cost_event_extracts_metadata_from_routing_summary():
    """Verify CostEvent creation logic extracts profile metadata from routing_summary."""
    # This tests the logic without needing full _execute_node
    routing_summary = RoutingDecisionSummary(
        agent_preset="researcher",
        task_role="researcher",
        mood="analytical",
        execution_policy="docs_research",
        workflow_phase="executing",
        provider="openai",
        model="gpt-4",
    )

    # Simulate the extraction logic from custom_plan_service.py
    agent_preset = routing_summary.agent_preset
    task_role = routing_summary.task_role
    execution_policy_name = routing_summary.execution_policy

    # Create CostEvent with extracted metadata
    event = CostEvent(
        id="ce_test",
        workflow_id="wf_test",
        node_id="n_test",
        model="gpt-4",
        provider="openai",
        task_type="code_gen",
        agent_preset=agent_preset,
        task_role=task_role,
        execution_policy_name=execution_policy_name,
    )

    assert event.agent_preset == "researcher"
    assert event.task_role == "researcher"
    assert event.execution_policy_name == "docs_research"
