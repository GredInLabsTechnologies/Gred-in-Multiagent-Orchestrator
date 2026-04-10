"""Tests that AgenticLoopService enforces execution_policy on tool calls."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tools.gimo_server.services.agentic_loop_service import AgenticLoopService
from tools.gimo_server.models.agent_routing import RoutingDecisionSummary
from tools.gimo_server.services.execution.execution_policy_service import ExecutionPolicyService


@pytest.mark.asyncio
async def test_agentic_loop_enforces_execution_policy():
    """Agentic loop checks execution_policy before executing tools."""
    # Create a routing summary with docs_research policy (allows read but not write)
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
    mock_tool_calls = [
        {
            "id": "call_1",
            "function": {"name": "write", "arguments": '{"path": "test.txt", "content": "foo"}'},
        }
    ]

    with (
        patch("tools.gimo_server.services.agentic_loop_service._resolve_bound_adapter") as mock_resolve,
        patch("tools.gimo_server.services.agentic_loop_service.ToolExecutor") as mock_executor_cls,
    ):
        mock_resolve.return_value = (mock_adapter, "openai", "gpt-4", "openai")

        # Configure mock adapter chat_with_tools
        mock_adapter.chat_with_tools = AsyncMock(side_effect=[
            {
                "content": None,
                "tool_calls": mock_tool_calls,
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "finish_reason": "tool_calls",
            },
            # Second call after tool denial
            {
                "content": "I cannot write files with this policy.",
                "tool_calls": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "finish_reason": "stop",
            },
        ])

        mock_executor = MagicMock()
        mock_executor.execute_tool_call = AsyncMock()
        mock_executor_cls.return_value = mock_executor

        result = await AgenticLoopService.run_node(
            workspace_root="/tmp/test",
            node_prompt="Write a file",
            routing_summary=summary,
        )

        # Tool should have been denied by execution_policy
        # The executor should NOT have been called
        assert mock_executor.execute_tool_call.call_count == 0
        # Check that the tool was logged as policy_denied
        assert len(result.tool_calls_log) == 1
        assert result.tool_calls_log[0]["status"] == "policy_denied"
        assert "execution policy" in result.tool_calls_log[0]["message"].lower()


@pytest.mark.asyncio
async def test_agentic_loop_allows_permitted_tool():
    """Agentic loop allows tools permitted by execution_policy."""
    # workspace_safe policy allows read
    summary = RoutingDecisionSummary(
        agent_preset="executor",
        task_role="executor",
        mood="assertive",
        execution_policy="workspace_safe",
        workflow_phase="executing",
        provider="openai",
        model="gpt-4",
    )

    mock_adapter = MagicMock()
    mock_tool_calls = [
        {
            "id": "call_1",
            "function": {"name": "read", "arguments": '{"path": "test.txt"}'},
        }
    ]

    with (
        patch("tools.gimo_server.services.agentic_loop_service._resolve_bound_adapter") as mock_resolve,
        patch("tools.gimo_server.services.agentic_loop_service.ToolExecutor") as mock_executor_cls,
    ):
        mock_resolve.return_value = (mock_adapter, "openai", "gpt-4", "openai")

        # Configure mock adapter chat_with_tools
        mock_adapter.chat_with_tools = AsyncMock(side_effect=[
            {
                "content": None,
                "tool_calls": mock_tool_calls,
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "finish_reason": "tool_calls",
            },
            # Second call after tool execution
            {
                "content": "File content retrieved.",
                "tool_calls": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "finish_reason": "stop",
            },
        ])

        mock_executor = MagicMock()
        mock_executor.execute_tool_call = AsyncMock(return_value={"status": "success", "data": {"content": "test"}})
        mock_executor_cls.return_value = mock_executor

        result = await AgenticLoopService.run_node(
            workspace_root="/tmp/test",
            node_prompt="Read a file",
            routing_summary=summary,
        )

        # Tool should have been executed
        assert mock_executor.execute_tool_call.call_count == 1
        assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_agentic_loop_without_execution_policy_backward_compat():
    """Agentic loop works without execution_policy (legacy mode)."""
    mock_adapter = MagicMock()
    mock_tool_calls = [
        {
            "id": "call_1",
            "function": {"name": "list", "arguments": '{"path": "."}'},
        }
    ]

    with (
        patch("tools.gimo_server.services.agentic_loop_service._resolve_bound_adapter") as mock_resolve,
        patch("tools.gimo_server.services.agentic_loop_service.ToolExecutor") as mock_executor_cls,
    ):
        mock_resolve.return_value = (mock_adapter, "openai", "gpt-4", "openai")

        # Configure mock adapter chat_with_tools
        mock_adapter.chat_with_tools = AsyncMock(side_effect=[
            {
                "content": None,
                "tool_calls": mock_tool_calls,
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "finish_reason": "tool_calls",
            },
            {
                "content": "Listed files.",
                "tool_calls": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "finish_reason": "stop",
            },
        ])

        mock_executor = MagicMock()
        mock_executor.execute_tool_call = AsyncMock(return_value={"status": "success", "data": {"files": []}})
        mock_executor_cls.return_value = mock_executor

        # Call without routing_summary (legacy mode)
        result = await AgenticLoopService.run_node(
            workspace_root="/tmp/test",
            node_prompt="List files",
            mood="executor",
            execution_policy=None,  # No policy specified
        )

        # Tool should execute without policy enforcement (legacy behavior)
        assert mock_executor.execute_tool_call.call_count == 1
        assert result.finish_reason == "stop"
