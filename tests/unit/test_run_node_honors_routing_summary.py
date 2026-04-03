"""Tests that run_node() honors routing_summary and uses allow_orchestrator_fallback correctly."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tools.gimo_server.services.agentic_loop_service import AgenticLoopService
from tools.gimo_server.models.agent_routing import RoutingDecisionSummary


@pytest.mark.asyncio
async def test_run_node_with_routing_summary_uses_summary_provider():
    """run_node extracts provider/model from routing_summary."""
    summary = RoutingDecisionSummary(
        agent_preset="researcher",
        task_role="researcher",
        mood="analytical",
        execution_policy="docs_research",
        workflow_phase="executing",
        provider="openai",
        model="gpt-4",
    )

    mock_adapter = MagicMock()
    with (
        patch("tools.gimo_server.services.agentic_loop_service._resolve_bound_adapter") as mock_resolve,
        patch.object(AgenticLoopService, "_run_loop", new_callable=AsyncMock) as mock_loop,
    ):
        mock_resolve.return_value = (mock_adapter, "openai", "gpt-4", "openai")
        mock_loop.return_value = MagicMock(response="done", usage={}, finish_reason="stop")

        await AgenticLoopService.run_node(
            workspace_root="/tmp/test",
            node_prompt="Test task",
            routing_summary=summary,
        )

        # Should call with allow_orchestrator_fallback=False
        mock_resolve.assert_called_once_with("openai", "gpt-4", False)


@pytest.mark.asyncio
async def test_run_node_with_routing_summary_uses_summary_policy():
    """run_node extracts execution_policy from routing_summary."""
    summary = RoutingDecisionSummary(
        agent_preset="researcher",
        task_role="researcher",
        mood="analytical",
        execution_policy="security_audit",
        workflow_phase="reviewing",
        provider="auto",
        model="auto",
    )

    mock_adapter = MagicMock()
    with (
        patch("tools.gimo_server.services.agentic_loop_service._resolve_bound_adapter") as mock_resolve,
        patch.object(AgenticLoopService, "_run_loop", new_callable=AsyncMock) as mock_loop,
    ):
        mock_resolve.return_value = (mock_adapter, "openai", "gpt-4", "openai")
        mock_loop.return_value = MagicMock(response="done", usage={}, finish_reason="stop")

        await AgenticLoopService.run_node(
            workspace_root="/tmp/test",
            node_prompt="Test task",
            routing_summary=summary,
        )

        # _run_loop should receive execution_policy from summary
        call_kwargs = mock_loop.call_args.kwargs
        assert call_kwargs["execution_policy"] == "security_audit"


@pytest.mark.asyncio
async def test_run_node_without_routing_summary_backward_compatible():
    """run_node works with legacy parameters when routing_summary=None."""
    mock_adapter = MagicMock()
    with (
        patch("tools.gimo_server.services.agentic_loop_service._resolve_bound_adapter") as mock_resolve,
        patch.object(AgenticLoopService, "_run_loop", new_callable=AsyncMock) as mock_loop,
    ):
        mock_resolve.return_value = (mock_adapter, "openai", "gpt-4", "openai")
        mock_loop.return_value = MagicMock(response="done", usage={}, finish_reason="stop")

        await AgenticLoopService.run_node(
            workspace_root="/tmp/test",
            node_prompt="Test task",
            mood="executor",
            execution_policy="workspace_safe",
            provider="openai",
            model="gpt-4",
        )

        # Should call with allow_orchestrator_fallback=True (default)
        mock_resolve.assert_called_once_with("openai", "gpt-4", True)


def test_resolve_bound_adapter_signature_accepts_allow_orchestrator_fallback():
    """_resolve_bound_adapter accepts allow_orchestrator_fallback parameter."""
    import inspect
    from tools.gimo_server.services.agentic_loop_service import _resolve_bound_adapter

    sig = inspect.signature(_resolve_bound_adapter)
    assert "allow_orchestrator_fallback" in sig.parameters
    assert sig.parameters["allow_orchestrator_fallback"].default is True
