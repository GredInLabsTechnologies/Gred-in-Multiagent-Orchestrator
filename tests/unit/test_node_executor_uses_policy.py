"""Tests that NodeExecutor uses execution_policy instead of role_profile."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tools.gimo_server.ops_models import WorkflowNode
from tools.gimo_server.services.graph.node_executor import NodeExecutorMixin


class MockEngine(NodeExecutorMixin):
    """Mock engine to test NodeExecutorMixin."""

    def __init__(self):
        self._provider_service = MagicMock()


@pytest.mark.asyncio
async def test_enforce_tool_governance_uses_execution_policy():
    """_enforce_tool_governance prefers execution_policy over role_profile."""
    engine = MockEngine()

    node = WorkflowNode(
        id="n_test",
        label="test",
        type="tool_call",
        config={
            "execution_policy": "docs_research",
            "role_profile": "executor",  # Should be ignored
            "tool_name": "read_file",  # Use correct tool name
        },
    )

    # Don't mock the policy, let it use the real one
    await engine._enforce_tool_governance(node=node, tool_name="read_file", args={})

    # Should not raise - read_file is allowed in docs_research


@pytest.mark.asyncio
async def test_enforce_tool_governance_denies_unauthorized_tool():
    """_enforce_tool_governance raises PermissionError for unauthorized tools."""
    engine = MockEngine()

    node = WorkflowNode(
        id="n_test",
        name="test",
        type="tool_call",
        config={
            "execution_policy": "read_only",
            "tool_name": "write",
        },
    )

    with patch("tools.gimo_server.services.execution_policy_service.ExecutionPolicyService.get_policy") as mock_get:
        mock_policy = MagicMock()
        mock_policy.assert_tool_allowed = MagicMock(side_effect=PermissionError("Tool not allowed"))
        mock_get.return_value = mock_policy

        with pytest.raises(PermissionError, match="denied tool"):
            await engine._enforce_tool_governance(node=node, tool_name="write", args={})


@pytest.mark.asyncio
async def test_enforce_tool_governance_legacy_role_profile():
    """_enforce_tool_governance falls back to role_profile when execution_policy is absent."""
    engine = MockEngine()

    node = WorkflowNode(
        id="n_test",
        label="test",
        type="tool_call",
        config={
            "role_profile": "executor",  # Legacy
            "tool_name": "any_tool",
        },
    )

    # Mock both assert_tool_allowed and get_role_profile to avoid real execution
    with (
        patch("tools.gimo_server.services.graph.node_executor.assert_tool_allowed") as mock_assert,
        patch("tools.gimo_server.services.graph.node_executor.get_role_profile") as mock_get_profile,
    ):
        mock_profile = MagicMock()
        mock_profile.hitl_required = False
        mock_get_profile.return_value = mock_profile

        # This should call legacy functions
        await engine._enforce_tool_governance(node=node, tool_name="any_tool", args={})

        # Verify legacy functions were called
        mock_assert.assert_called_once_with("executor", "any_tool")
        mock_get_profile.assert_called_once_with("executor")


@pytest.mark.asyncio
async def test_enforce_tool_governance_hitl_required():
    """_enforce_tool_governance enforces HITL when policy requires it."""
    engine = MockEngine()

    node = WorkflowNode(
        id="n_test",
        label="test",
        type="tool_call",
        config={
            "execution_policy": "workspace_safe",
            "tool_name": "test_tool",
        },
        agent="test_agent",
    )

    with (
        patch("tools.gimo_server.services.execution_policy_service.ExecutionPolicyService.get_policy") as mock_get_policy,
        patch("tools.gimo_server.services.hitl_gate_service.HitlGateService.gate_tool_call") as mock_gate,
    ):
        # Mock policy that allows the tool and requires confirmation
        mock_policy = MagicMock()
        mock_policy.allowed_tools = frozenset({"test_tool"})
        mock_policy.requires_confirmation = frozenset({"test_tool"})
        mock_get_policy.return_value = mock_policy

        # HITL denies
        mock_gate.return_value = "deny"

        with pytest.raises(PermissionError, match="HITL denied"):
            await engine._enforce_tool_governance(node=node, tool_name="test_tool", args={})

        mock_gate.assert_called_once()


@pytest.mark.asyncio
async def test_enforce_tool_governance_no_governance():
    """_enforce_tool_governance allows all tools when no governance is configured."""
    engine = MockEngine()

    node = WorkflowNode(
        id="n_test",
        name="test",
        type="tool_call",
        config={
            "tool_name": "anything",
        },
    )

    # Should not raise
    await engine._enforce_tool_governance(node=node, tool_name="anything", args={})
