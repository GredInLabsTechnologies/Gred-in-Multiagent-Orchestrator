"""
Unit tests for AgenticLoopService helper functions.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tools.gimo_server.services.agentic_loop_service import (
    AgenticResult,
    AgenticLoopService,
    ThreadExecutionBusyError,
    _generate_workspace_tree,
    _build_messages_from_thread,
)
from tools.gimo_server.models.conversation import GimoThread, GimoTurn, GimoItem
from tools.gimo_server.services.conversation_service import ConversationService
from tools.gimo_server.engine.moods import get_mood_profile


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

    def test_thread_runtime_context_prefers_agent_preset_catalog(self, tmp_path: Path):
        thread = GimoThread(
            workspace_root=str(tmp_path),
            title="Preset thread",
            mood="neutral",
            agent_preset="researcher",
            workflow_phase="planning",
        )

        mood, mood_profile, task_role, workflow_phase, execution_policy = AgenticLoopService._resolve_thread_runtime_context(
            thread
        )

        assert mood == "analytical"
        assert mood_profile.name == "analytical"
        assert task_role == "researcher"
        assert workflow_phase == "planning"
        assert execution_policy == "docs_research"

    def test_thread_runtime_context_uses_legacy_mood_only_at_compat_edge(self, tmp_path: Path):
        thread = GimoThread(
            workspace_root=str(tmp_path),
            title="Legacy thread",
            mood="forensic",
            workflow_phase="planning",
        )
        thread._legacy_missing_agent_preset = True

        mood, mood_profile, task_role, workflow_phase, execution_policy = AgenticLoopService._resolve_thread_runtime_context(
            thread
        )

        assert mood == "analytical"
        assert mood_profile.name == "analytical"
        assert task_role == "researcher"
        assert workflow_phase == "planning"
        assert execution_policy == "docs_research"

    def test_thread_runtime_context_prefers_explicit_execution_policy_metadata(self, tmp_path: Path):
        thread = GimoThread(
            workspace_root=str(tmp_path),
            title="Explicit policy thread",
            mood="neutral",
            agent_preset="researcher",
            workflow_phase="planning",
            metadata={"execution_policy": "read_only"},
        )

        _, _, task_role, workflow_phase, execution_policy = AgenticLoopService._resolve_thread_runtime_context(thread)

        assert task_role == "researcher"
        assert workflow_phase == "planning"
        assert execution_policy == "read_only"


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


class _FakeGics:
    def __init__(self, seed: dict | None = None):
        self.seed = seed or {}
        self.records = {}

    def get(self, key: str):
        return self.seed.get(key) or self.records.get(key)

    def put(self, key: str, value: dict):
        self.records[key] = value

    def scan(self, prefix: str = "", include_fields: bool = True):
        out = []
        merged = {**self.seed, **self.records}
        for key, value in merged.items():
            if key.startswith(prefix):
                out.append({"key": key, "fields": value})
        return out


@pytest.mark.asyncio
async def test_run_reserved_passes_explicit_policy_from_thread_context(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ConversationService, "THREADS_DIR", tmp_path / "threads")
    thread = GimoThread(
        workspace_root=str(tmp_path),
        title="Conversation",
        agent_preset="researcher",
        workflow_phase="planning",
    )
    ConversationService.save_thread(thread)

    captured: dict[str, object] = {}

    async def _fake_run_loop(**kwargs):
        captured.update(kwargs)
        return AgenticResult(response="ok")

    monkeypatch.setattr(
        "tools.gimo_server.services.agentic_loop_service._resolve_orchestrator_adapter",
        lambda: (object(), "provider", "model"),
    )
    monkeypatch.setattr(AgenticLoopService, "_run_loop", _fake_run_loop)

    result = await AgenticLoopService._run_reserved(
        thread_id=thread.id,
        user_message="Investigate docs",
        workspace_root=str(tmp_path),
    )

    assert result.response == "ok"
    assert captured["execution_policy"] == "docs_research"
    assert captured["mood"] == "analytical"


@pytest.mark.asyncio
async def test_run_loop_uses_predictive_max_tokens(tmp_path: Path):
    gics = _FakeGics(
        {
            "ops:task:plan_node:test-model": {
                "samples": 5,
                "avg_output_tokens": 10,
            }
        }
    )
    adapter = AsyncMock()
    adapter.chat_with_tools = AsyncMock(
        return_value={
            "content": "done",
            "tool_calls": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            "finish_reason": "stop",
        }
    )

    with patch.object(AgenticLoopService, "_get_gics", return_value=gics):
        result = await AgenticLoopService._run_loop(
            adapter=adapter,
            provider_id="test-provider",
            model="test-model",
            workspace_root=str(tmp_path),
            token="system",
            mood="neutral",
            mood_profile=get_mood_profile("neutral"),
            messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
            max_turns=1,
            temperature=0.0,
            tools=[],
            task_key="plan_node",
        )

    assert result.response == "done"
    assert adapter.chat_with_tools.await_args.kwargs["max_tokens"] == 13


@pytest.mark.asyncio
async def test_run_loop_enforces_turn_budget(tmp_path: Path):
    adapter = AsyncMock()
    adapter.chat_with_tools = AsyncMock(
        return_value={
            "content": "expensive",
            "tool_calls": [],
            "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
            "finish_reason": "stop",
        }
    )

    with patch.object(AgenticLoopService, "_calculate_usage_cost", return_value=999.0):
        result = await AgenticLoopService._run_loop(
            adapter=adapter,
            provider_id="test-provider",
            model="test-model",
            workspace_root=str(tmp_path),
            token="system",
            mood="neutral",
            mood_profile=get_mood_profile("neutral"),
            messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
            max_turns=1,
            temperature=0.0,
            tools=[],
            task_key="agentic_chat",
        )

    assert result.finish_reason == "turn_budget_exhausted"


@pytest.mark.asyncio
async def test_run_loop_persists_execution_proofs(tmp_path: Path):
    gics = _FakeGics()
    adapter = AsyncMock()
    adapter.chat_with_tools = AsyncMock(
        side_effect=[
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": json.dumps({"path": "x.txt"})},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "finish_reason": "tool_calls",
            },
            {
                "content": "done",
                "tool_calls": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "finish_reason": "stop",
            },
        ]
    )

    with patch.object(AgenticLoopService, "_get_gics", return_value=gics), patch(
        "tools.gimo_server.services.agentic_loop_service.ToolExecutor.execute_tool_call",
        new=AsyncMock(return_value={"status": "success", "message": "ok", "data": {"content": "x"}}),
    ):
        result = await AgenticLoopService._run_loop(
            adapter=adapter,
            provider_id="test-provider",
            model="test-model",
            workspace_root=str(tmp_path),
            token="system",
            mood="neutral",
            mood_profile=get_mood_profile("neutral"),
            messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
            max_turns=2,
            temperature=0.0,
            tools=[{"type": "function", "function": {"name": "read_file"}}],
            task_key="agentic_chat",
            thread_id="thread_proof",
            persist_conversation=False,
            allow_hitl=False,
        )

    assert result.response == "done"
    proof_keys = [key for key in gics.records if key.startswith("ops:proof:thread_proof:")]
    assert len(proof_keys) == 1


@pytest.mark.asyncio
async def test_run_loop_recovers_from_corrupt_proof_history_and_still_persists_new_proofs(tmp_path: Path):
    gics = _FakeGics(
        {
            "ops:proof:thread_bad:proof_legacy": {
                "proof_id": "proof_legacy",
                "prev_proof_id": "",
                "thread_id": "thread_bad",
                "tool_name": "read_file",
                "input_hash": "a",
                "output_hash": "b",
                "mood": "forensic",
                "cost_usd": 0.0,
                "timestamp": 1.0,
            }
        }
    )
    adapter = AsyncMock()
    adapter.chat_with_tools = AsyncMock(
        side_effect=[
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": json.dumps({"path": "x.txt"})},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "finish_reason": "tool_calls",
            },
            {
                "content": "done",
                "tool_calls": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "finish_reason": "stop",
            },
        ]
    )

    with patch.object(AgenticLoopService, "_get_gics", return_value=gics), patch(
        "tools.gimo_server.services.agentic_loop_service.ToolExecutor.execute_tool_call",
        new=AsyncMock(return_value={"status": "success", "message": "ok", "data": {"content": "x"}}),
    ):
        result = await AgenticLoopService._run_loop(
            adapter=adapter,
            provider_id="test-provider",
            model="test-model",
            workspace_root=str(tmp_path),
            token="system",
            mood="neutral",
            mood_profile=get_mood_profile("neutral"),
            messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
            max_turns=2,
            temperature=0.0,
            tools=[{"type": "function", "function": {"name": "read_file"}}],
            task_key="agentic_chat",
            thread_id="thread_bad",
            persist_conversation=False,
            allow_hitl=False,
        )

    assert result.response == "done"
    proof_keys = sorted(key for key in {**gics.seed, **gics.records} if key.startswith("ops:proof:thread_bad:"))
    assert len(proof_keys) == 2
    with patch.object(AgenticLoopService, "_get_gics", return_value=gics):
        payload = AgenticLoopService.get_thread_proofs("thread_bad")
    assert payload["verified"] is False
    assert len(payload["proofs"]) == 2


def test_get_thread_proofs_marks_malformed_records_unverified():
    gics = _FakeGics(
        {
            "ops:proof:thread_bad:proof_1": {
                "proof_id": "proof_1",
                "prev_proof_id": "",
                "thread_id": "thread_bad",
                "tool_name": "read_file",
                "input_hash": "a",
                "output_hash": "b",
                "mood": "forensic",
                "cost_usd": 0.0,
                "timestamp": 1.0,
            }
        }
    )

    with patch.object(AgenticLoopService, "_get_gics", return_value=gics):
        payload = AgenticLoopService.get_thread_proofs("thread_bad")

    assert payload["thread_id"] == "thread_bad"
    assert payload["verified"] is False
    assert len(payload["proofs"]) == 1
    assert payload["proofs"][0]["proof_id"] == "proof_1"


@pytest.mark.asyncio
async def test_run_rejects_concurrent_execution_for_same_thread(tmp_path: Path):
    original_threads_dir = ConversationService.THREADS_DIR
    ConversationService.THREADS_DIR = tmp_path / "threads"
    try:
        thread = ConversationService.create_thread(workspace_root=str(tmp_path), title="busy")
        AgenticLoopService.reserve_thread_execution(thread.id)
        with pytest.raises(ThreadExecutionBusyError):
            await AgenticLoopService.run(
                thread_id=thread.id,
                user_message="hi",
                workspace_root=str(tmp_path),
                token="system",
            )
    finally:
        AgenticLoopService.release_thread_execution(thread.id)
        ConversationService.THREADS_DIR = original_threads_dir


@pytest.mark.asyncio
async def test_run_loop_plan_proposed_preserves_conversation_turns(tmp_path: Path):
    original_threads_dir = ConversationService.THREADS_DIR
    ConversationService.THREADS_DIR = tmp_path / "threads"
    adapter = AsyncMock()
    adapter.chat_with_tools = AsyncMock(
        return_value={
            "content": None,
            "tool_calls": [
                {
                    "id": "call_plan",
                    "type": "function",
                    "function": {"name": "propose_plan", "arguments": json.dumps({"title": "Ship it"})},
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "finish_reason": "tool_calls",
        }
    )

    try:
        thread = ConversationService.create_thread(workspace_root=str(tmp_path), title="plan")
        stale_thread = ConversationService.get_thread(thread.id)
        assert stale_thread is not None

        with patch(
            "tools.gimo_server.services.agentic_loop_service.ToolExecutor.execute_tool_call",
            new=AsyncMock(
                return_value={
                    "status": "plan_proposed",
                    "message": "Plan proposed",
                    "data": {
                        "title": "Ship it",
                        "objective": "Deliver safely",
                        "tasks": [
                            {
                                "id": "t1",
                                "title": "Investigate auth flow",
                                "description": "Inspect the current flow",
                                "agent_mood": "forensic",
                                "agent_rationale": "Need careful analysis",
                            }
                        ],
                    },
                }
            ),
        ), patch(
            "tools.gimo_server.services.notification_service.NotificationService.publish",
            new=AsyncMock(return_value=None),
        ):
            result = await AgenticLoopService._run_loop(
                adapter=adapter,
                provider_id="test-provider",
                model="test-model",
                workspace_root=str(tmp_path),
                token="system",
                mood="neutral",
                mood_profile=get_mood_profile("neutral"),
                messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "plan it"}],
                max_turns=1,
                temperature=0.0,
                tools=[{"type": "function", "function": {"name": "propose_plan"}}],
                task_key="agentic_chat",
                thread_id=thread.id,
                thread=stale_thread,
                persist_conversation=True,
                allow_hitl=False,
            )

        stored = ConversationService.get_thread(thread.id)
        assert result.finish_reason == "plan_proposed"
        assert stored is not None
        assert stored.proposed_plan["title"] == "Ship it"
        assert stored.proposed_plan["objective"] == "Deliver safely"
        assert stored.workflow_phase == "awaiting_approval"
        assert stored.proposed_plan["tasks"][0]["agent_preset"] == "researcher"
        assert stored.proposed_plan["tasks"][0]["source_shape"] == "conversational_plan"
        assert "task_descriptor" in stored.proposed_plan["tasks"][0]
        assert "task_fingerprint" in stored.proposed_plan["tasks"][0]
        assert len(stored.turns) == 2
        assert any(item.type == "tool_call" for turn in stored.turns for item in turn.items)
        assert any(item.content == "Plan proposed. Please review and approve to continue." for turn in stored.turns for item in turn.items)
    finally:
        ConversationService.THREADS_DIR = original_threads_dir
