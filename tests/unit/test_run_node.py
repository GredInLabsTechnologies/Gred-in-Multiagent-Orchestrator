"""Tests for AgenticLoopService.run_node() — P2 plan-node execution."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.gimo_server.services.agentic_loop_service import AgenticLoopService, AgenticResult


def _mock_adapter(responses):
    """Create a mock adapter that yields responses in sequence."""
    adapter = AsyncMock()
    adapter.chat_with_tools = AsyncMock(side_effect=responses)
    return adapter


def _final_response(content="Done", usage=None):
    """LLM response with no tool_calls (final answer)."""
    return {
        "content": content,
        "tool_calls": [],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "finish_reason": "stop",
    }


def _tool_call_response(tool_name, arguments, content="", usage=None):
    """LLM response with a single tool_call."""
    return {
        "content": content,
        "tool_calls": [
            {
                "id": "call_0",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments),
                },
            }
        ],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "finish_reason": "tool_calls",
    }


class TestRunNode:
    @patch("tools.gimo_server.services.agentic_loop_service._resolve_orchestrator_adapter")
    @patch("tools.gimo_server.services.agentic_loop_service.CostService.calculate_cost", return_value=0.001)
    def test_basic_run_returns_agentic_result(self, _mock_cost, mock_resolve):
        adapter = _mock_adapter([_final_response("Hello from node")])
        mock_resolve.return_value = (adapter, "test-provider", "test-model", "openai")

        result = asyncio.run(AgenticLoopService.run_node(
            workspace_root="/tmp",
            node_prompt="Say hello",
            mood="executor",
        ))

        assert isinstance(result, AgenticResult)
        assert result.response == "Hello from node"
        assert result.turns_used == 1
        assert result.finish_reason == "stop"
        adapter.chat_with_tools.assert_called_once()

    @patch("tools.gimo_server.services.agentic_loop_service._resolve_orchestrator_adapter")
    @patch("tools.gimo_server.services.agentic_loop_service.CostService.calculate_cost", return_value=0.0)
    def test_does_not_use_conversation_service(self, _mock_cost, mock_resolve):
        adapter = _mock_adapter([_final_response("OK")])
        mock_resolve.return_value = (adapter, "test", "model", "openai")

        with patch("tools.gimo_server.services.agentic_loop_service.ConversationService") as mock_cs:
            result = asyncio.run(AgenticLoopService.run_node(
                workspace_root="/tmp",
                node_prompt="test",
            ))
            # ConversationService should NOT be called in run_node
            mock_cs.get_thread.assert_not_called()
            mock_cs.add_turn.assert_not_called()
            mock_cs.append_item.assert_not_called()

    @patch("tools.gimo_server.services.agentic_loop_service._resolve_orchestrator_adapter")
    @patch("tools.gimo_server.services.agentic_loop_service.CostService.calculate_cost", return_value=0.0)
    def test_meta_tools_return_error_in_node_context(self, _mock_cost, mock_resolve):
        """ask_user in a node context should return error (no interactive mode)."""
        # First call: LLM calls ask_user, second call: LLM gives final answer
        adapter = _mock_adapter([
            _tool_call_response("ask_user", {"question": "Which file?"}),
            _final_response("Completed without asking"),
        ])
        mock_resolve.return_value = (adapter, "test", "model", "openai")

        result = asyncio.run(AgenticLoopService.run_node(
            workspace_root="/tmp",
            node_prompt="do something",
            mood="neutral",
        ))

        assert isinstance(result, AgenticResult)
        # The node should have processed ask_user as error and continued
        assert result.turns_used >= 1
        # Check that the tool log captured the error
        ask_user_logs = [log for log in result.tool_calls_log if log["name"] == "ask_user"]
        assert len(ask_user_logs) == 1
        assert ask_user_logs[0]["status"] == "error"

    @patch("tools.gimo_server.services.agentic_loop_service._resolve_orchestrator_adapter")
    @patch("tools.gimo_server.services.agentic_loop_service.CostService.calculate_cost", return_value=0.0)
    def test_usage_accumulation(self, _mock_cost, mock_resolve):
        adapter = _mock_adapter([
            _tool_call_response("list_files", {"path": "."}, usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}),
            _final_response("Done", usage={"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}),
        ])
        mock_resolve.return_value = (adapter, "test", "model", "openai")

        result = asyncio.run(AgenticLoopService.run_node(
            workspace_root="/tmp",
            node_prompt="list files",
            mood="neutral",
        ))

        assert result.usage["prompt_tokens"] == 300
        assert result.usage["completion_tokens"] == 150
        assert result.usage["total_tokens"] == 450

    @patch("tools.gimo_server.services.agentic_loop_service._resolve_orchestrator_adapter")
    @patch("tools.gimo_server.services.agentic_loop_service.CostService.calculate_cost", return_value=0.0)
    def test_invalid_mood_defaults_to_executor(self, _mock_cost, mock_resolve):
        adapter = _mock_adapter([_final_response("OK")])
        mock_resolve.return_value = (adapter, "test", "model", "openai")

        result = asyncio.run(AgenticLoopService.run_node(
            workspace_root="/tmp",
            node_prompt="test",
            mood="invalid_mood",
        ))

        assert isinstance(result, AgenticResult)
        # Should not crash, falls back to executor
        assert result.response == "OK"
