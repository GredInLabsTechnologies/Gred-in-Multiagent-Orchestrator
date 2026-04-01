"""Tests that GraphEngine can use ProfileRouterService for canonical routing."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tools.gimo_server.ops_models import WorkflowNode
from tools.gimo_server.services.graph.node_executor import NodeExecutorMixin
from tools.gimo_server.models.agent_routing import RoutingDecisionSummary


class MockEngine(NodeExecutorMixin):
    """Mock engine to test NodeExecutorMixin."""

    def __init__(self):
        self._provider_service = MagicMock()
        self.state = MagicMock()
        self.state.data = {}


@pytest.mark.asyncio
async def test_execute_llm_call_uses_profile_router_when_agent_preset():
    """_execute_llm_call uses ProfileRouterService when node has agent_preset."""
    engine = MockEngine()

    node = WorkflowNode(
        id="n_test",
        label="test",
        type="llm_call",
        config={
            "agent_preset": "researcher",
            "task_type": "code_review",
            "workflow_phase": "reviewing",
            "prompt": "Review this code",
        },
    )

    mock_routing_summary = RoutingDecisionSummary(
        agent_preset="researcher",
        task_role="researcher",
        mood="analytical",
        execution_policy="docs_research",
        workflow_phase="reviewing",
        provider="openai",
        model="gpt-4",
    )

    with (
        patch("tools.gimo_server.services.profile_router_service.ProfileRouterService.route") as mock_route,
        patch.object(engine._provider_service, "generate", new_callable=AsyncMock) as mock_generate,
    ):
        mock_decision = MagicMock()
        mock_decision.summary = mock_routing_summary
        mock_decision.binding.model = "gpt-4"
        mock_decision.binding.provider = "openai"
        mock_decision.profile.agent_preset = "researcher"
        mock_decision.profile.execution_policy = "docs_research"
        mock_route.return_value = mock_decision

        mock_generate.return_value = {
            "content": "Review complete",
            "provider": "openai",
            "model": "gpt-4",
            "tokens_used": 100,
            "cost_usd": 0.01,
        }

        result = await engine._execute_llm_call(node)

        # Should call ProfileRouterService.route
        mock_route.assert_called_once()
        call_kwargs = mock_route.call_args.kwargs
        assert call_kwargs["requested_preset"] == "researcher"

        # Should store routing_decision_summary in node.config
        assert "routing_decision_summary" in node.config
        assert node.config["routing_decision_summary"]["agent_preset"] == "researcher"
        assert node.config["routing_decision_summary"]["execution_policy"] == "docs_research"

        # Should override selected_model and execution_policy
        assert node.config["selected_model"] == "gpt-4"
        assert node.config["execution_policy"] == "docs_research"


@pytest.mark.asyncio
async def test_execute_llm_call_skips_routing_when_already_routed():
    """_execute_llm_call skips ProfileRouterService if routing_decision_summary exists."""
    engine = MockEngine()

    node = WorkflowNode(
        id="n_test",
        label="test",
        type="llm_call",
        config={
            "agent_preset": "researcher",
            "routing_decision_summary": {
                "agent_preset": "researcher",
                "task_role": "researcher",
                "mood": "analytical",
                "execution_policy": "docs_research",
                "workflow_phase": "reviewing",
                "provider": "openai",
                "model": "gpt-4",
            },
            "selected_model": "gpt-4",
            "prompt": "Review this code",
        },
    )

    with (
        patch("tools.gimo_server.services.profile_router_service.ProfileRouterService.route") as mock_route,
        patch.object(engine._provider_service, "generate", new_callable=AsyncMock) as mock_generate,
    ):
        mock_generate.return_value = {
            "content": "Review complete",
            "provider": "openai",
            "model": "gpt-4",
            "tokens_used": 100,
            "cost_usd": 0.01,
        }

        result = await engine._execute_llm_call(node)

        # Should NOT call ProfileRouterService again
        mock_route.assert_not_called()


@pytest.mark.asyncio
async def test_execute_llm_call_without_agent_preset_uses_legacy():
    """_execute_llm_call uses legacy selected_model when no agent_preset."""
    engine = MockEngine()

    node = WorkflowNode(
        id="n_test",
        label="test",
        type="llm_call",
        config={
            "selected_model": "gpt-3.5-turbo",
            "prompt": "Generate code",
        },
    )

    with (
        patch("tools.gimo_server.services.profile_router_service.ProfileRouterService.route") as mock_route,
        patch.object(engine._provider_service, "generate", new_callable=AsyncMock) as mock_generate,
    ):
        mock_generate.return_value = {
            "content": "Code generated",
            "provider": "openai",
            "model": "gpt-3.5-turbo",
            "tokens_used": 50,
            "cost_usd": 0.005,
        }

        result = await engine._execute_llm_call(node)

        # Should NOT call ProfileRouterService
        mock_route.assert_not_called()

        # Should use selected_model from config
        assert "routing_decision_summary" not in node.config


@pytest.mark.asyncio
async def test_execute_llm_call_routing_builds_task_descriptor():
    """_execute_llm_call builds TaskDescriptor from node config."""
    engine = MockEngine()

    node = WorkflowNode(
        id="n_test",
        label="security_audit",
        type="llm_call",
        config={
            "agent_preset": "reviewer",
            "task_type": "security_review",
            "complexity": "high",
            "risk_level": "high",
            "cost_ceiling": 0.50,
            "budget_mode": "premium",
            "prompt": "Audit this code",
        },
    )

    mock_routing_summary = RoutingDecisionSummary(
        agent_preset="reviewer",
        task_role="reviewer",
        mood="cautious",  # Use valid mood from enum
        execution_policy="security_audit",
        workflow_phase="executing",
        provider="openai",
        model="gpt-4",
    )

    with (
        patch("tools.gimo_server.services.profile_router_service.ProfileRouterService.route") as mock_route,
        patch.object(engine._provider_service, "generate", new_callable=AsyncMock) as mock_generate,
    ):
        mock_decision = MagicMock()
        mock_decision.summary = mock_routing_summary
        mock_route.return_value = mock_decision

        mock_generate.return_value = {
            "content": "Audit complete",
            "provider": "openai",
            "model": "gpt-4",
            "tokens_used": 200,
            "cost_usd": 0.02,
        }

        result = await engine._execute_llm_call(node)

        # Verify TaskDescriptor was built correctly
        call_kwargs = mock_route.call_args.kwargs
        descriptor = call_kwargs["descriptor"]
        assert descriptor.task_id == "n_test"
        # Title should be node.label, which defaults to node.id if not set
        assert descriptor.title in ("security_audit", "n_test")  # Either label or id
        assert descriptor.task_type == "security_review"
        assert descriptor.complexity_band == "high"
        assert descriptor.risk_band == "high"

        # Verify routing was called with correct preset
        assert call_kwargs["requested_preset"] == "reviewer"
