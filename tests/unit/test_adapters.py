import asyncio
import pytest
import respx
from httpx import Response
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock, call
from tools.gimo_server.adapters import (
    AgentStatus,
    ClaudeCodeAdapter,
    CodexAdapter,
    GeminiAdapter,
    GenericCLIAdapter,
    OpenAICompatibleAdapter,
)
from tools.gimo_server.services.model_router_service import ModelRouterService, RoutingDecision
from tools.gimo_server.services.graph_engine import GraphEngine
from tools.gimo_server.ops_models import WorkflowGraph, WorkflowNode



def _build_mock_process(
    *,
    stdout_lines: list[bytes] | None = None,
    stderr_lines: list[bytes] | None = None,
    returncode: int | None = None,
):
    process = MagicMock()
    process.returncode = returncode
    process.stdin = SimpleNamespace(write=AsyncMock(), drain=AsyncMock())

    out_iter = iter(stdout_lines or [b""])
    err_iter = iter(stderr_lines or [b""])

    async def mock_readline_stdout():
        return next(out_iter, b"")

    async def mock_readline_stderr():
        return next(err_iter, b"")

    async def mock_wait():
        return returncode

    process.stdout.readline = mock_readline_stdout
    process.stderr.readline = mock_readline_stderr
    process.wait = mock_wait
    return process


@pytest.mark.asyncio
async def test_generic_cli_adapter_spawn():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(returncode=None)
        mock_exec.return_value = mock_process

        adapter = GenericCLIAdapter(["echo", "hello"])
        session = await adapter.spawn("Test task")

        assert session is not None
        assert await session.get_status() == AgentStatus.RUNNING

        # Verify task was sent to stdin
        mock_process.stdin.write.assert_called_once_with(b"Test task\n")
        mock_process.stdin.drain.assert_awaited()


@pytest.mark.asyncio
async def test_generic_cli_session_result():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(
            stdout_lines=[
                b'PROPOSAL:{"id":"a1","tool":"file_write","params":{"path":"x.py"}}',
                b'PROPOSAL:{"id":"a2","tool":"shell_exec","params":{"cmd":"pytest"}}',
                b"Line 1",
                b"Line 2",
                b"",
            ],
            stderr_lines=[b""],
            returncode=0,
        )
        mock_exec.return_value = mock_process

        adapter = GenericCLIAdapter(["dummy"])
        session = await adapter.spawn("Test")

        # Wait a bit for background reader
        await asyncio.sleep(0.1)

        proposals = await session.capture_proposals()
        assert [p.id for p in proposals] == ["a1", "a2"]

        with patch("tools.gimo_server.adapters.generic_cli.ToolRegistryService.is_allowed", return_value=True):
            await session.allow("a1")
        await session.deny("a2", reason="unsafe")

        result = await session.get_result()
        assert result.status == AgentStatus.COMPLETED
        assert "Line 1" in result.output
        assert "Line 2" in result.output
        assert result.metrics["proposal_count"] == 2
        assert result.metrics["decisions"]["a1"] == "allowed"
        assert result.metrics["decisions"]["a2"] == "denied:unsafe"

        mock_process.stdin.write.assert_has_calls(
            [
                call(b"Test\n"),
                call(b"ALLOW a1\n"),
                call(b"DENY a2 reason=unsafe\n"),
            ]
        )
        assert mock_process.stdin.drain.await_count == 3


@pytest.mark.asyncio
async def test_generic_cli_emits_trust_events_on_allow_deny():
    captured_events = []

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(
            stdout_lines=[
                b'PROPOSAL:{"id":"a1","tool":"file_write","params":{"path":"src/x.py"}}',
                b'PROPOSAL:{"id":"a2","tool":"shell_exec","params":{"cmd":"pytest"}}',
                b"",
            ],
            stderr_lines=[b""],
            returncode=0,
        )
        mock_exec.return_value = mock_process

        adapter = GenericCLIAdapter(
            ["dummy"],
            trust_event_sink=captured_events.append,
            model_name="generic-cli",
            actor="agent:test",
        )
        session = await adapter.spawn("Test", context={"task_type": "refactor"})
        await asyncio.sleep(0.1)

        with patch("tools.gimo_server.adapters.generic_cli.ToolRegistryService.is_allowed", return_value=True):
            await session.allow("a1")
        await session.deny("a2", reason="unsafe")

    assert len(captured_events) == 2
    assert captured_events[0]["outcome"] == "approved"
    assert captured_events[0]["tool"] == "file_write"
    assert captured_events[0]["task_type"] == "refactor"
    assert captured_events[1]["outcome"] == "rejected"
    assert captured_events[1]["tool"] == "shell_exec"


@pytest.mark.asyncio
async def test_claude_code_adapter_spawn():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(returncode=None)
        mock_exec.return_value = mock_process

        adapter = ClaudeCodeAdapter(binary_path="claude-test")
        session = await adapter.spawn("Fix bugs")

        assert session is not None
        # Verify CLI arguments include stream output format
        mock_exec.assert_called_once()
        args, _ = mock_exec.call_args
        assert args[0] == "claude-test"
        assert args[1] == "execute"
        assert args[2] == "Fix bugs"
        assert args[3] == "--output-format"
        assert args[4] == "stream-json"


@pytest.mark.asyncio
async def test_claude_code_session_intercepts_mcp_proposals_and_metrics():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(
            stdout_lines=[
                b'MCP_PRE_TOOL:{"id":"c1","tool":"shell_exec","params":{"cmd":"ls"}}',
                b'METRICS:{"tokens_used":321,"duration_ms":987}',
                b"done",
                b"",
            ],
            stderr_lines=[b""],
            returncode=0,
        )
        mock_exec.return_value = mock_process

        adapter = ClaudeCodeAdapter(binary_path="claude-test")
        session = await adapter.spawn("Audit")

        await asyncio.sleep(0.1)

        proposals = await session.capture_proposals()
        assert len(proposals) == 1
        assert proposals[0].id == "c1"
        assert proposals[0].tool == "shell_exec"

        with patch("tools.gimo_server.adapters.generic_cli.ToolRegistryService.is_allowed", return_value=True):
            await session.allow("c1")
        result = await session.get_result()

        assert result.status == AgentStatus.COMPLETED
        assert result.metrics["tokens_used"] == 321
        assert result.metrics["duration_ms"] == 987
        mock_process.stdin.write.assert_has_calls(
            [
                call(b"MCP_ALLOW c1\n"),
            ]
        )


@pytest.mark.asyncio
async def test_claude_adapter_emits_trust_event_on_allow():
    captured_events = []

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(
            stdout_lines=[
                b'MCP_PRE_TOOL:{"id":"c1","tool":"shell_exec","params":{"cmd":"ls"}}',
                b"",
            ],
            stderr_lines=[b""],
            returncode=0,
        )
        mock_exec.return_value = mock_process

        adapter = ClaudeCodeAdapter(
            binary_path="claude-test",
            trust_event_sink=captured_events.append,
            model_name="claude-code",
            actor="agent:claude-test",
        )
        session = await adapter.spawn("Audit", context={"task_type": "review"})
        await asyncio.sleep(0.1)

        with patch("tools.gimo_server.adapters.generic_cli.ToolRegistryService.is_allowed", return_value=True):
            await session.allow("c1")

    assert len(captured_events) == 1
    event = captured_events[0]
    assert event["outcome"] == "approved"
    assert event["tool"] == "shell_exec"
    assert event["task_type"] == "review"
    assert event["model"] == "claude-code"


@pytest.mark.asyncio
async def test_generic_cli_blocks_unregistered_tool_on_allow():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(
            stdout_lines=[
                b'PROPOSAL:{"id":"a1","tool":"destructive_tool","params":{"path":"/tmp/x"}}',
                b"",
            ],
            stderr_lines=[b""],
            returncode=0,
        )
        mock_exec.return_value = mock_process

        adapter = GenericCLIAdapter(["dummy"])
        session = await adapter.spawn("Test")
        await asyncio.sleep(0.1)

        with patch("tools.gimo_server.adapters.generic_cli.ToolRegistryService.is_allowed", return_value=False):
            with pytest.raises(PermissionError):
                await session.allow("a1")

        assert session._decision_log["a1"].startswith("blocked:not_in_tool_registry")


@pytest.mark.asyncio
async def test_generic_cli_write_tool_requires_idempotency_key():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(
            stdout_lines=[
                b'PROPOSAL:{"id":"a1","tool":"file_write","params":{"path":"/tmp/x"}}',
                b"",
            ],
            stderr_lines=[b""],
            returncode=0,
        )
        mock_exec.return_value = mock_process

        adapter = GenericCLIAdapter(["dummy"])
        session = await adapter.spawn("Test")
        await asyncio.sleep(0.1)

        tool_entry = type("ToolEntryStub", (), {"risk": "write", "allowed_roles": ["operator", "admin"]})()
        with patch("tools.gimo_server.adapters.generic_cli.ToolRegistryService.get_tool", return_value=tool_entry), patch(
            "tools.gimo_server.adapters.generic_cli.ToolRegistryService.is_allowed", return_value=True
        ):
            with pytest.raises(PermissionError):
                await session.allow("a1")

        assert session._decision_log["a1"] == "blocked:missing_idempotency_key"


@pytest.mark.asyncio
async def test_generic_cli_write_tool_blocks_duplicate_idempotency_key():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(
            stdout_lines=[
                b'PROPOSAL:{"id":"a1","tool":"file_write","params":{"path":"/tmp/x","idempotency_key":"k1"}}',
                b"",
            ],
            stderr_lines=[b""],
            returncode=0,
        )
        mock_exec.return_value = mock_process

        adapter = GenericCLIAdapter(["dummy"])
        session = await adapter.spawn("Test")
        await asyncio.sleep(0.1)

        tool_entry = type("ToolEntryStub", (), {"risk": "write", "allowed_roles": ["operator", "admin"]})()
        with patch("tools.gimo_server.adapters.generic_cli.ToolRegistryService.get_tool", return_value=tool_entry), patch(
            "tools.gimo_server.adapters.generic_cli.ToolRegistryService.is_allowed", return_value=True
        ), patch(
            "tools.gimo_server.adapters.generic_cli.StorageService.register_tool_call_idempotency_key", return_value=False
        ):
            with pytest.raises(PermissionError):
                await session.allow("a1")

        assert session._decision_log["a1"] == "blocked:duplicate_idempotency_key"


@pytest.mark.asyncio
async def test_generic_cli_reports_discovered_tools_from_proposals():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(
            stdout_lines=[
                b'PROPOSAL:{"id":"a1","tool":"custom_tool","params":{}}',
                b"",
            ],
            stderr_lines=[b""],
            returncode=0,
        )
        mock_exec.return_value = mock_process

        with patch("tools.gimo_server.adapters.generic_cli.ToolRegistryService.report_tool") as mock_report:
            adapter = GenericCLIAdapter(["dummy"])
            await adapter.spawn("Test")
            await asyncio.sleep(0.1)
            assert mock_report.called
            assert mock_report.call_args.kwargs["name"] == "custom_tool"


@pytest.mark.asyncio
async def test_codex_adapter_spawn_and_session_protocol():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(
            stdout_lines=[
                b'CODEX_PRE_TOOL:{"id":"x1","tool":"shell_exec","params":{"cmd":"pytest"}}',
                b'CODEX_METRICS:{"tokens_used":123,"duration_ms":456}',
                b"",
            ],
            stderr_lines=[b""],
            returncode=0,
        )
        mock_exec.return_value = mock_process

        adapter = CodexAdapter(binary_path="codex-test")
        session = await adapter.spawn("Run tests")

        await asyncio.sleep(0.1)
        proposals = await session.capture_proposals()
        assert len(proposals) == 1
        assert proposals[0].id == "x1"
        assert proposals[0].tool == "shell_exec"

        with patch("tools.gimo_server.adapters.generic_cli.ToolRegistryService.is_allowed", return_value=True):
            await session.allow("x1")
        result = await session.get_result()

        assert result.metrics["tokens_used"] == 123
        assert result.metrics["duration_ms"] == 456
        mock_process.stdin.write.assert_has_calls([call(b"CODEX_ALLOW x1\n")])


@pytest.mark.asyncio
async def test_gemini_adapter_spawn_and_session_protocol():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = _build_mock_process(
            stdout_lines=[
                b'GEMINI_PRE_TOOL:{"id":"g1","tool":"file_write","params":{"path":"a.py"}}',
                b'GEMINI_METRICS:{"tokens_used":77,"duration_ms":111}',
                b"",
            ],
            stderr_lines=[b""],
            returncode=0,
        )
        mock_exec.return_value = mock_process

        adapter = GeminiAdapter(binary_path="gemini-test")
        session = await adapter.spawn("Write file")

        await asyncio.sleep(0.1)
        proposals = await session.capture_proposals()
        assert len(proposals) == 1
        assert proposals[0].id == "g1"
        assert proposals[0].tool == "file_write"

        with patch("tools.gimo_server.adapters.generic_cli.ToolRegistryService.is_allowed", return_value=True):
            await session.allow("g1")
        result = await session.get_result()

        assert result.metrics["tokens_used"] == 77
        assert result.metrics["duration_ms"] == 111
        mock_process.stdin.write.assert_has_calls([call(b"GEMINI_ALLOW g1\n")])
@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_adapter_spawn_and_result():
    base_url = "http://localhost:1234/v1"
    model_name = "test-model"
    adapter = OpenAICompatibleAdapter(base_url=base_url, model_name=model_name)
    
    # Mock the LLM response
    respx.post(f"{base_url}/chat/completions").mock(return_value=Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": "Hello world"}, "index": 0, "finish_reason": "stop"}],
        "usage": {"total_tokens": 10}
    }))
    
    session = await adapter.spawn("Repeat 'Hello world'")
    assert session is not None
    
    result = await session.get_result()
    assert result.status == AgentStatus.COMPLETED
    assert result.output == "Hello world"
    assert result.metrics["tokens_used"] == 10

@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_adapter_tool_call():
    base_url = "http://localhost:1234/v1"
    model_name = "test-model"
    adapter = OpenAICompatibleAdapter(base_url=base_url, model_name=model_name)
    
    # Mock the first response with a tool call
    respx.post(f"{base_url}/chat/completions").mock(return_value=Response(200, json={
        "choices": [{
            "message": {
                "role": "assistant", 
                "content": None,
                "tool_calls": [{
                    "id": "call_123",
                    "type": "function",
                    "function": {"name": "test_tool", "arguments": '{"arg1": "val1"}'}
                }]
            }, 
            "index": 0
        }],
        "usage": {"total_tokens": 20}
    }))
    
    session = await adapter.spawn("Call test_tool")
    
    # Wait for background task to update status
    import asyncio
    for _ in range(10):
        if await session.get_status() == AgentStatus.PAUSED:
            break
        await asyncio.sleep(0.1)
        
    assert await session.get_status() == AgentStatus.PAUSED
    proposals = await session.capture_proposals()
    assert len(proposals) == 1
    assert proposals[0].tool == "test_tool"
    assert proposals[0].params == {"arg1": "val1"}

    # Mock the second response after tool result
    respx.post(f"{base_url}/chat/completions").mock(return_value=Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": "Tool executed successfully"}, "index": 0}],
        "usage": {"total_tokens": 5}
    }))

    await session.allow("call_123")
    
    # Wait for background task
    for _ in range(10):
        if await session.get_status() == AgentStatus.COMPLETED:
            break
        await asyncio.sleep(0.1)

    result = await session.get_result()
    assert result.status == AgentStatus.COMPLETED
    assert result.output == "Tool executed successfully"
    assert result.metrics["tokens_used"] == 25

@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_adapter_deny():
    base_url = "http://localhost:1234/v1"
    model_name = "test-model"
    adapter = OpenAICompatibleAdapter(base_url=base_url, model_name=model_name)
    
    respx.post(f"{base_url}/chat/completions").mock(return_value=Response(200, json={
        "choices": [{
            "message": {
                "role": "assistant", 
                "content": None,
                "tool_calls": [{"id": "call_456", "type": "function", "function": {"name": "unsafe_tool", "arguments": "{}"}}]
            }, 
            "index": 0
        }],
        "usage": {"total_tokens": 10}
    }))
    
    session = await adapter.spawn("Call unsafe_tool")
    await asyncio.sleep(0.2)
    
    # Mock response after deny
    respx.post(f"{base_url}/chat/completions").mock(return_value=Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": "I understand you denied that."}, "index": 0}],
        "usage": {"total_tokens": 5}
    }))
    
    await session.deny("call_456", reason="Not safe")
    await asyncio.sleep(0.2)
    
    result = await session.get_result()
    assert result.output == "I understand you denied that."

@pytest.mark.asyncio
@respx.mock
async def test_openai_compatible_adapter_error():
    base_url = "http://localhost:1234/v1"
    model_name = "test-model"
    adapter = OpenAICompatibleAdapter(base_url=base_url, model_name=model_name)
    
    respx.post(f"{base_url}/chat/completions").mock(return_value=Response(500))
    
    session = await adapter.spawn("Fail")
    await asyncio.sleep(0.2)
    
    result = await session.get_result()
    assert result.status == AgentStatus.FAILED
    assert "error" in result.metrics

# ── Model Router & Budget Enforcement ─────────────────────

@pytest.mark.asyncio
async def test_model_router_policy_selection():
    """Verify router chooses models based on task type (Consolidated)."""
    router = ModelRouterService()
    node = WorkflowNode(id="n1", type="llm_call", config={"task_type": "security_review"})
    decision = await router.choose_model(node, state={})
    assert decision.model == "opus"
    assert "policy" in decision.reason

@pytest.mark.asyncio
async def test_model_router_degrades_on_low_budget():
    """Verify router falls back to cheaper model when budget is tight."""
    router = ModelRouterService()
    node = WorkflowNode(id="n2", type="llm_call", config={"task_type": "code_generation"})
    decision = await router.choose_model(
        node, state={"budget": {"max_cost_usd": 10.0}, "budget_counters": {"cost_usd": 9.5}}
    )
    assert decision.model == "haiku"
    assert "low_budget" in decision.reason

@pytest.mark.asyncio
async def test_provider_budget_enforcement_aborts():
    """Verify GraphEngine aborts execution when provider budget is exhausted."""
    nodes = [WorkflowNode(id="n1", type="agent_task", config={"pattern": "single"})]
    graph = WorkflowGraph(id="g1", nodes=nodes, edges=[])
    
    mock_storage = MagicMock()
    mock_storage.cost.get_total_spend.return_value = 0.0
    mock_storage.cost.get_provider_spend.return_value = 100.0 # Exhausted
    
    engine = GraphEngine(graph, storage=mock_storage)
    
    with patch.object(engine._model_router, "check_provider_budget", return_value="provider_budget_exhausted: anthropic"):
        state = await engine.execute()
        assert "provider_budget_exhausted" in str(state.data.get("pause_reason", ""))
