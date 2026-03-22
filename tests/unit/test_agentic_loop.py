"""
Unit tests for AgenticLoopService helper functions.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from tools.gimo_server.services.agentic_loop_service import (
    AgenticResult,
    _generate_workspace_tree,
    _build_messages_from_thread,
)
from tools.gimo_server.models.conversation import GimoThread, GimoTurn, GimoItem


@pytest.fixture
def mock_thread(tmp_path: Path):
    """Mock conversation thread."""
    thread = GimoThread(
        id="thread_test123",
        workspace_root=str(tmp_path),
        title="Test Thread"
    )
    # Add a user turn
    user_turn = GimoTurn(agent_id="user")
    user_turn.items.append(GimoItem(type="text", content="Hello"))
    thread.turns.append(user_turn)
    return thread


class TestAgenticLoopHelpers:
    """Tests for helper functions."""

    def test_generate_workspace_tree(self, tmp_path: Path):
        """Should generate tree structure."""
        # Create structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("code")
        (tmp_path / "README.md").write_text("readme")
        (tmp_path / ".git").mkdir()  # Should be ignored

        tree = _generate_workspace_tree(str(tmp_path))

        assert "src" in tree
        assert "app.py" in tree
        assert "README.md" in tree
        assert ".git" not in tree  # Hidden dirs excluded

    def test_generate_workspace_tree_empty(self, tmp_path: Path):
        """Should handle empty workspace."""
        tree = _generate_workspace_tree(str(tmp_path))
        assert "empty workspace" in tree.lower() or tree.strip() == ""

    def test_generate_workspace_tree_max_entries(self, tmp_path: Path):
        """Should respect max_entries limit."""
        # Create many files
        for i in range(150):
            (tmp_path / f"file{i}.txt").write_text("test")

        tree = _generate_workspace_tree(str(tmp_path), max_entries=50)

        # Should have truncation marker
        lines = tree.split("\n")
        assert len(lines) <= 55  # max_entries + some margin for dirs

    def test_build_messages_from_thread(self, mock_thread):
        """Should convert thread to messages list."""
        system_prompt = "You are GIMO"
        messages = _build_messages_from_thread(mock_thread.turns, system_prompt)

        # Should have system prompt + user message
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert "GIMO" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Hello"

    def test_build_messages_with_tool_calls(self):
        """Should reconstruct assistant messages with tool calls."""
        turns = [
            GimoTurn(
                agent_id="orchestrator",
                items=[
                    GimoItem(
                        type="tool_call",
                        content=json.dumps({"path": "test.txt"}),
                        metadata={"tool_call_id": "call_1", "tool_name": "read_file"}
                    ),
                    GimoItem(
                        type="tool_result",
                        content="file content",
                        metadata={"tool_call_id": "call_1"}
                    ),
                ]
            )
        ]

        messages = _build_messages_from_thread(turns, "system prompt")

        # Should have tool messages
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0]["content"] == "file content"


class TestAgenticResult:
    """Tests for AgenticResult dataclass."""

    def test_agentic_result_defaults(self):
        """Should have correct default values."""
        result = AgenticResult(response="test")

        assert result.response == "test"
        assert result.tool_calls_log == []
        assert result.usage == {}
        assert result.turns_used == 0
        assert result.finish_reason == "stop"

    def test_agentic_result_with_data(self):
        """Should store provided data."""
        result = AgenticResult(
            response="test response",
            tool_calls_log=[{"name": "read_file"}],
            usage={"total_tokens": 100},
            turns_used=3,
            finish_reason="length"
        )

        assert result.response == "test response"
        assert len(result.tool_calls_log) == 1
        assert result.usage["total_tokens"] == 100
        assert result.turns_used == 3
        assert result.finish_reason == "length"
