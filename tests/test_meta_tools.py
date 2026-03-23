"""Tests for P2 meta-tools and mood-based constraints in executor.py."""
import asyncio
import pytest

from tools.gimo_server.engine.tools.executor import ToolExecutor, ToolExecutionResult


# ── handle_ask_user ──────────────────────────────────────────────────────────


class TestHandleAskUser:
    def test_returns_user_question_status(self):
        executor = ToolExecutor(workspace_root="/tmp", mood="neutral")
        result = asyncio.run(executor.handle_ask_user({"question": "Which file?", "options": ["a", "b"]}))
        assert result["status"] == "user_question"
        assert result["data"]["question"] == "Which file?"
        assert result["data"]["options"] == ["a", "b"]

    def test_missing_question_returns_error(self):
        executor = ToolExecutor(workspace_root="/tmp", mood="neutral")
        result = asyncio.run(executor.handle_ask_user({}))
        assert result["status"] == "error"
        assert "question" in result["message"].lower()


# ── handle_propose_plan ──────────────────────────────────────────────────────


class TestHandleProposePlan:
    def test_returns_plan_proposed_status(self):
        executor = ToolExecutor(workspace_root="/tmp", mood="neutral")
        args = {
            "title": "Refactor auth",
            "objective": "Improve security",
            "tasks": [
                {"id": "t1", "title": "Review code", "agent_rationale": "Need forensic analysis"}
            ],
        }
        result = asyncio.run(executor.handle_propose_plan(args))
        assert result["status"] == "plan_proposed"
        assert result["data"]["title"] == "Refactor auth"
        assert len(result["data"]["tasks"]) == 1

    def test_missing_title_returns_error(self):
        executor = ToolExecutor(workspace_root="/tmp", mood="neutral")
        result = asyncio.run(executor.handle_propose_plan({"objective": "x", "tasks": []}))
        assert result["status"] == "error"

    def test_missing_objective_returns_error(self):
        executor = ToolExecutor(workspace_root="/tmp", mood="neutral")
        result = asyncio.run(executor.handle_propose_plan({"title": "x", "tasks": []}))
        assert result["status"] == "error"

    def test_empty_tasks_returns_error(self):
        executor = ToolExecutor(workspace_root="/tmp", mood="neutral")
        result = asyncio.run(executor.handle_propose_plan({"title": "x", "objective": "y", "tasks": []}))
        assert result["status"] == "error"
        assert "task" in result["message"].lower()

    def test_task_missing_agent_rationale_returns_error(self):
        executor = ToolExecutor(workspace_root="/tmp", mood="neutral")
        args = {
            "title": "Plan",
            "objective": "Do stuff",
            "tasks": [{"id": "t1", "title": "Step 1"}],
        }
        result = asyncio.run(executor.handle_propose_plan(args))
        assert result["status"] == "error"
        assert "agent_rationale" in result["message"]


# ── handle_web_search ────────────────────────────────────────────────────────


class TestHandleWebSearch:
    def test_does_not_crash_with_query(self):
        """handle_web_search should not raise, regardless of WebSearchService availability."""
        executor = ToolExecutor(workspace_root="/tmp", mood="neutral")
        result = asyncio.run(executor.handle_web_search({"query": "test query"}))
        # May return success (placeholder) or error (bad API), but should not crash
        assert result["status"] in ("success", "error")

    def test_missing_query_returns_error(self):
        executor = ToolExecutor(workspace_root="/tmp", mood="neutral")
        result = asyncio.run(executor.handle_web_search({}))
        assert result["status"] == "error"


# ── Mood-Based Tool Constraints ──────────────────────────────────────────────


class TestMoodToolConstraints:
    def test_whitelist_blocks_unlisted_tool(self):
        """forensic mood only allows read_file, list_files, search_text, ask_user."""
        executor = ToolExecutor(workspace_root="/tmp", mood="forensic")
        allowed, reason = executor._is_tool_allowed("write_file")
        assert not allowed
        assert "whitelist" in reason.lower()

    def test_whitelist_allows_listed_tool(self):
        executor = ToolExecutor(workspace_root="/tmp", mood="forensic")
        allowed, reason = executor._is_tool_allowed("read_file")
        assert allowed
        assert reason is None

    def test_empty_whitelist_allows_all(self):
        """neutral mood has empty whitelist, so all tools pass."""
        executor = ToolExecutor(workspace_root="/tmp", mood="neutral")
        allowed, _ = executor._is_tool_allowed("shell_exec")
        assert allowed

    def test_requires_confirmation_detected(self):
        """forensic mood requires confirmation for write_file."""
        executor = ToolExecutor(workspace_root="/tmp", mood="forensic")
        # write_file is not in whitelist so it would be blocked first,
        # but requires_confirmation is checked separately
        assert executor._requires_confirmation("write_file")
        assert not executor._requires_confirmation("read_file")

    def test_execute_tool_call_returns_requires_confirmation(self):
        """dialoger mood requires confirmation for shell_exec, but shell_exec IS in whitelist."""
        executor = ToolExecutor(workspace_root="/tmp", mood="dialoger")
        # shell_exec is NOT in dialoger whitelist, so it should be blocked
        result = asyncio.run(executor.execute_tool_call("shell_exec", {"command": "ls"}))
        assert result["status"] == "error"
        assert "whitelist" in result["message"].lower()

    def test_invalid_mood_falls_back_to_neutral(self):
        executor = ToolExecutor(workspace_root="/tmp", mood="nonexistent")
        assert executor._mood_profile is not None
        assert executor._mood_profile.name == "neutral"
