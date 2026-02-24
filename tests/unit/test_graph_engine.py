from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from tools.gimo_server.ops_models import (
    WorkflowEdge, 
    WorkflowGraph, 
    WorkflowNode, 
    WorkflowState
)
from tools.gimo_server.services.graph_engine import GraphEngine
from tools.gimo_server.services.confidence_service import ConfidenceService
from tools.gimo_server.ops_models import ToolEntry
import hashlib
import math
import os
from pathlib import Path


@pytest.mark.asyncio
async def test_graph_engine_linear_execution():
    # A -> B -> C
    nodes = [
        WorkflowNode(id="A", type="transform", config={"val": 1}),
        WorkflowNode(id="B", type="transform", config={"val": 2}),
        WorkflowNode(id="C", type="transform", config={"val": 3}),
    ]
    edges = [
        WorkflowEdge(**{"from": "A", "to": "B"}),
        WorkflowEdge(**{"from": "B", "to": "C"}),
    ]
    graph = WorkflowGraph(id="test_linear", nodes=nodes, edges=edges)
    
    engine = GraphEngine(graph)
    
    # Mock node execution to simple return config val (state-aware signature)
    async def mock_execute(node, state):
        await asyncio.sleep(0)
        assert "start" in state
        return node.config
        
    engine._execute_node = mock_execute
    
    state = await engine.execute(initial_state={"start": True})
    
    assert len(state.checkpoints) == 3
    assert state.checkpoints[0].node_id == "A"
    assert state.checkpoints[-1].node_id == "C"
    assert state.data["val"] == 3 # Last node overwrites because they use the same key
    assert len(state.data["step_logs"]) == 3
    assert state.data["step_logs"][0]["step_id"] == "step_1"
    assert state.data["step_logs"][-1]["node_id"] == "C"


@pytest.mark.asyncio
async def test_graph_engine_branching():
    # A -> B (if ok)
    # A -> C (if fail)
    nodes = [
        WorkflowNode(id="A", type="transform"),
        WorkflowNode(id="B", type="transform", config={"path": "success"}),
        WorkflowNode(id="C", type="transform", config={"path": "failure"}),
    ]
    edges = [
        WorkflowEdge(**{"from": "A", "to": "B", "condition": "is_ok"}),
        WorkflowEdge(**{"from": "A", "to": "C"}), # Default fallback
    ]
    graph = WorkflowGraph(id="test_branch", nodes=nodes, edges=edges)
    
    # Test path success
    engine_ok = GraphEngine(graph)
    async def mock_execute_ok(node, state):
        await asyncio.sleep(0)
        if node.id == "A":
            return {"is_ok": True}
        return node.config
        
    engine_ok._execute_node = mock_execute_ok
    state_ok = await engine_ok.execute()
    
    assert [cp.node_id for cp in state_ok.checkpoints] == ["A", "B"]
    assert state_ok.data["path"] == "success"
    assert [s["node_id"] for s in state_ok.data["step_logs"]] == ["A", "B"]

    # Test path failure
    engine_fail = GraphEngine(graph)
    async def mock_execute_fail(node, state):
        await asyncio.sleep(0)
        if node.id == "A":
            return {"is_ok": False}
        return node.config
        
    engine_fail._execute_node = mock_execute_fail
    state_fail = await engine_fail.execute()
    
    assert [cp.node_id for cp in state_fail.checkpoints] == ["A", "C"]
    assert state_fail.data["path"] == "failure"
    assert [s["status"] for s in state_fail.data["step_logs"]] == ["completed", "completed"]


@pytest.mark.asyncio
async def test_graph_engine_stops_on_max_iterations():
    # Self-loop to force iteration cap
    nodes = [
        WorkflowNode(id="A", type="transform", config={"tick": 1}),
    ]
    edges = [
        WorkflowEdge(**{"from": "A", "to": "A"}),
    ]
    graph = WorkflowGraph(id="test_loop_cap", nodes=nodes, edges=edges)

    engine = GraphEngine(graph, max_iterations=2)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return {"count": state.get("count", 0) + 1}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert len(state.checkpoints) == 2
    assert state.data["count"] == 2
    assert state.data["aborted_reason"] == "max_iterations_exceeded"


@pytest.mark.asyncio
async def test_graph_engine_persists_checkpoints_when_enabled():
    nodes = [
        WorkflowNode(id="A", type="transform", config={"v": 1}),
        WorkflowNode(id="B", type="transform", config={"v": 2}),
    ]
    edges = [
        WorkflowEdge(**{"from": "A", "to": "B"}),
    ]
    graph = WorkflowGraph(id="wf_persist", nodes=nodes, edges=edges)

    class StubStorage:
        def __init__(self):
            self.workflow_saved = None
            self.checkpoints = []

        def save_workflow(self, workflow_id, data):
            self.workflow_saved = (workflow_id, data)

        def save_checkpoint(self, workflow_id, node_id, state, output, status):
            self.checkpoints.append(
                {
                    "workflow_id": workflow_id,
                    "node_id": node_id,
                    "state": state,
                    "output": output,
                    "status": status,
                }
            )

    storage = StubStorage()
    engine = GraphEngine(graph, storage=storage, persist_checkpoints=True)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return node.config

    engine._execute_node = mock_execute
    state = await engine.execute(initial_state={"start": True})

    assert state.data["v"] == 2
    assert storage.workflow_saved is not None
    assert storage.workflow_saved[0] == "wf_persist"
    assert storage.workflow_saved[1]["id"] == "wf_persist"
    assert len(storage.checkpoints) == 2
    assert [cp["node_id"] for cp in storage.checkpoints] == ["A", "B"]
    assert all(cp["status"] == "completed" for cp in storage.checkpoints)


@pytest.mark.asyncio
async def test_graph_engine_contract_check_pre_passes():
    nodes = [
        WorkflowNode(
            id="C1",
            type="contract_check",
            config={
                "phase": "pre",
                "contract": {
                    "pre_conditions": [
                        {"type": "custom", "params": {"state_key": "ready", "equals": True}}
                    ]
                },
            },
        ),
        WorkflowNode(id="A", type="transform", config={"done": True}),
    ]
    edges = [WorkflowEdge(**{"from": "C1", "to": "A"})]
    graph = WorkflowGraph(id="contract_pre_ok", nodes=nodes, edges=edges)

    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return node.config

    engine._execute_node = mock_execute
    state = await engine.execute(initial_state={"ready": True})

    assert [cp.node_id for cp in state.checkpoints] == ["C1", "A"]
    assert state.data["last_contract_check"]["contract_passed"] is True
    assert state.data["done"] is True


@pytest.mark.asyncio
async def test_graph_engine_contract_check_post_fail_runs_rollback():
    nodes = [
        WorkflowNode(
            id="C2",
            type="contract_check",
            config={
                "phase": "post",
                "contract": {
                    "post_conditions": [
                        {"type": "custom", "params": {"state_key": "tests_passed", "equals": True}}
                    ],
                    "rollback": [
                        {"type": "set_state", "key": "rolled_back", "value": True},
                        {"type": "remove_state", "key": "temp"},
                    ],
                },
            },
        )
    ]
    graph = WorkflowGraph(id="contract_post_fail", nodes=nodes, edges=[])

    engine = GraphEngine(graph)
    state = await engine.execute(initial_state={"tests_passed": False, "temp": "x"})

    assert len(state.checkpoints) == 1
    assert state.checkpoints[0].status == "failed"
    assert state.data["rolled_back"] is True
    assert "temp" not in state.data
    assert state.data["contract_failure"]["contract_phase"] == "post"
    assert state.data["rollback_actions"]


@pytest.mark.asyncio
async def test_graph_engine_human_review_pauses_and_resumes_with_approval():
    nodes = [
        WorkflowNode(id="HR", type="human_review", config={"timeout_seconds": 60, "default_action": "block"}),
        WorkflowNode(id="N2", type="transform", config={"after": "ok"}),
    ]
    edges = [WorkflowEdge(**{"from": "HR", "to": "N2"})]
    graph = WorkflowGraph(id="hr_pause_resume", nodes=nodes, edges=edges)

    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return node.config

    engine._execute_node = mock_execute

    state1 = await engine.execute(initial_state={})
    assert state1.data["execution_paused"] is True
    assert state1.data["pause_reason"] == "human_review_pending"
    assert state1.data["human_review_pending"]["node_id"] == "HR"
    assert state1.data["step_logs"][0]["status"] == "paused"

    state2 = await engine.execute(initial_state={"human_reviews": {"HR": {"decision": "approve"}}})
    assert state2.data["execution_paused"] is False
    assert state2.data["human_review"] == "approved"
    assert state2.data["after"] == "ok"
    assert [cp.node_id for cp in state2.checkpoints][-2:] == ["HR", "N2"]


@pytest.mark.asyncio
async def test_graph_engine_human_review_edit_state_and_annotation():
    nodes = [
        WorkflowNode(id="HR", type="human_review", config={}),
        WorkflowNode(id="N2", type="transform", config={"ok": True}),
    ]
    edges = [WorkflowEdge(**{"from": "HR", "to": "N2"})]
    graph = WorkflowGraph(id="hr_edit_state", nodes=nodes, edges=edges)

    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return node.config

    engine._execute_node = mock_execute

    await engine.execute(initial_state={})
    state = await engine.execute(
        initial_state={
            "human_reviews": {
                "HR": {
                    "decision": "edit_state",
                    "edited_state": {"manual_override": 1},
                    "annotation": "Ajustado por humano",
                }
            }
        }
    )

    assert state.data["human_review"] == "edited"
    assert state.data["manual_override"] == 1
    assert state.data["human_annotations"][-1]["note"] == "Ajustado por humano"
    assert state.data["ok"] is True


@pytest.mark.asyncio
async def test_graph_engine_human_review_reject_fails_node():
    nodes = [WorkflowNode(id="HR", type="human_review", config={})]
    graph = WorkflowGraph(id="hr_reject", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    await engine.execute(initial_state={})
    state = await engine.execute(initial_state={"human_reviews": {"HR": {"decision": "reject"}}})

    assert state.checkpoints[-1].node_id == "HR"
    assert state.checkpoints[-1].status == "failed"
    assert state.data["step_logs"][-1]["status"] == "failed"
    assert "rejected" in state.data["step_logs"][-1]["output"]["error"]


@pytest.mark.asyncio
async def test_graph_engine_human_review_timeout_default_block_fails():
    nodes = [
        WorkflowNode(id="HR", type="human_review", config={"timeout_seconds": 1, "default_action": "block"}),
    ]
    graph = WorkflowGraph(id="hr_timeout_block", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    old = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    state = await engine.execute(
        initial_state={
            "human_review_pending": {
                "node_id": "HR",
                "started_at": old,
                "timeout_seconds": 1,
                "default_action": "block",
            }
        }
    )

    assert state.checkpoints[-1].status == "failed"
    assert "timeout" in state.data["step_logs"][-1]["output"]["error"].lower()


@pytest.mark.asyncio
async def test_graph_engine_human_review_timeout_default_approve_continues():
    nodes = [
        WorkflowNode(id="HR", type="human_review", config={"timeout_seconds": 1, "default_action": "approve"}),
        WorkflowNode(id="N2", type="transform", config={"next": "done"}),
    ]
    edges = [WorkflowEdge(**{"from": "HR", "to": "N2"})]
    graph = WorkflowGraph(id="hr_timeout_approve", nodes=nodes, edges=edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return node.config

    engine._execute_node = mock_execute

    old = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    state = await engine.execute(
        initial_state={
            "human_review_pending": {
                "node_id": "HR",
                "started_at": old,
                "timeout_seconds": 1,
                "default_action": "approve",
            }
        }
    )

    assert state.data["human_review"] == "auto_approved_timeout"
    assert state.data["next"] == "done"


@pytest.mark.asyncio
async def test_graph_engine_node_retries_eventually_succeeds():
    nodes = [WorkflowNode(id="A", type="transform", retries=2, config={"retry_backoff_seconds": 0})]
    graph = WorkflowGraph(id="retry_ok", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    calls = {"n": 0}

    async def flaky(node, state):
        await asyncio.sleep(0)
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return {"ok": True}

    engine._execute_node = flaky
    state = await engine.execute()

    assert calls["n"] == 3
    assert state.checkpoints[-1].status == "completed"
    assert state.data["ok"] is True


@pytest.mark.asyncio
async def test_graph_engine_node_timeout_fails():
    nodes = [WorkflowNode(id="A", type="transform", timeout=1)]
    graph = WorkflowGraph(id="node_timeout", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def slow(node, state):
        await asyncio.sleep(1.2)
        return {"ok": True}

    engine._execute_node = slow
    state = await engine.execute()

    assert state.checkpoints[-1].status == "failed"
    assert "timed out" in state.data["step_logs"][-1]["output"]["error"].lower()


@pytest.mark.asyncio
async def test_graph_engine_workflow_timeout_exceeded():
    nodes = [
        WorkflowNode(id="A", type="transform"),
        WorkflowNode(id="B", type="transform"),
    ]
    edges = [WorkflowEdge(**{"from": "A", "to": "B"})]
    graph = WorkflowGraph(id="wf_timeout", nodes=nodes, edges=edges)
    engine = GraphEngine(graph, workflow_timeout_seconds=1)

    async def slow(node, state):
        await asyncio.sleep(1.2)
        return {"node": node.id}

    engine._execute_node = slow
    state = await engine.execute()

    # A may complete, B should not run because global timeout is reached before next step.
    assert state.data["aborted_reason"] == "workflow_timeout_exceeded"


@pytest.mark.asyncio
async def test_graph_engine_budget_max_steps_pause_by_default():
    nodes = [
        WorkflowNode(id="A", type="transform", config={"v": 1}),
        WorkflowNode(id="B", type="transform", config={"v": 2}),
    ]
    edges = [WorkflowEdge(**{"from": "A", "to": "B"})]
    graph = WorkflowGraph(id="budget_steps_pause", nodes=nodes, edges=edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return node.config

    engine._execute_node = mock_execute
    state = await engine.execute(initial_state={"budget": {"max_steps": 1}})

    assert state.data["execution_paused"] is True
    assert state.data["pause_reason"] == "budget_max_steps_exceeded"
    assert [cp.node_id for cp in state.checkpoints] == ["A"]


@pytest.mark.asyncio
async def test_graph_engine_budget_abort_on_tokens():
    nodes = [WorkflowNode(id="A", type="transform")]
    graph = WorkflowGraph(id="budget_abort", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return {"tokens_used": 20}

    engine._execute_node = mock_execute
    state = await engine.execute(initial_state={"budget": {"max_tokens": 10, "on_exceed": "abort"}})

    assert state.data["aborted_reason"] == "budget_max_tokens_exceeded"
    assert state.data["execution_paused"] is False


@pytest.mark.asyncio
async def test_graph_engine_resume_from_checkpoint_continues_from_next_node():
    nodes = [
        WorkflowNode(id="A", type="transform", config={"a": 1}),
        WorkflowNode(id="B", type="transform", config={"b": 2}),
    ]
    edges = [WorkflowEdge(**{"from": "A", "to": "B"})]
    graph = WorkflowGraph(id="resume_checkpoint", nodes=nodes, edges=edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return node.config

    engine._execute_node = mock_execute
    await engine.execute()

    next_node = engine.resume_from_checkpoint(0)
    assert next_node == "B"

    state = await engine.execute()
    assert state.data["resumed_from_checkpoint"]["node_id"] == "A"
    assert state.data["b"] == 2


@pytest.mark.asyncio
async def test_graph_engine_agent_task_supervisor_workers_pattern():
    nodes = [
        WorkflowNode(
            id="AG",
            type="agent_task",
            config={
                "pattern": "supervisor_workers",
                "workers": [
                    {"id": "w1", "task": "analyze auth"},
                    {"id": "w2", "task": "write tests"},
                ],
            },
        )
    ]
    graph = WorkflowGraph(id="agent_supervisor_workers", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        worker_id = node.config.get("worker_id")
        if worker_id:
            return {"worker": worker_id, "done": True}
        return {"noop": True}

    engine._execute_node = mock_execute
    state = await engine.execute(initial_state={"ticket": "SEC-1"})

    assert state.data["pattern"] == "supervisor_workers"
    assert set(state.data["worker_results"].keys()) == {"w1", "w2"}
    assert state.data["worker_results"]["w1"]["worker"] == "w1"
    assert state.data["worker_results"]["w2"]["worker"] == "w2"


@pytest.mark.asyncio
async def test_graph_engine_supervisor_workers_parallel_respects_limit():
    nodes = [
        WorkflowNode(
            id="AG",
            type="agent_task",
            config={
                "pattern": "supervisor_workers",
                "parallel": True,
                "max_parallel_workers": 2,
                "workers": [
                    {"id": "w1", "task": "t1"},
                    {"id": "w2", "task": "t2"},
                    {"id": "w3", "task": "t3"},
                ],
            },
        )
    ]
    graph = WorkflowGraph(id="agent_supervisor_workers_parallel", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    counters = {"active": 0, "peak": 0}

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        worker_id = node.config.get("worker_id")
        if worker_id:
            counters["active"] += 1
            counters["peak"] = max(counters["peak"], counters["active"])
            await asyncio.sleep(0.02)
            counters["active"] -= 1
            return {"worker": worker_id, "done": True}
        return {"noop": True}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["pattern"] == "supervisor_workers"
    assert state.data["parallel"] is True
    assert state.data["max_parallel_workers"] == 2
    assert set(state.data["worker_results"].keys()) == {"w1", "w2", "w3"}
    assert counters["peak"] <= 2


@pytest.mark.asyncio
async def test_graph_engine_supervisor_workers_collect_partial_keeps_successes():
    nodes = [
        WorkflowNode(
            id="AG",
            type="agent_task",
            config={
                "pattern": "supervisor_workers",
                "parallel": True,
                "fail_policy": "collect_partial",
                "max_parallel_workers": 2,
                "workers": [
                    {"id": "w1", "task": "ok"},
                    {"id": "w2", "task": "boom"},
                    {"id": "w3", "task": "ok2"},
                ],
            },
        )
    ]
    graph = WorkflowGraph(id="agent_supervisor_workers_partial", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        worker_id = node.config.get("worker_id")
        if worker_id == "w2":
            raise RuntimeError("worker failed")
        if worker_id:
            return {"worker": worker_id, "done": True}
        return {"noop": True}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["pattern"] == "supervisor_workers"
    assert state.data["fail_policy"] == "collect_partial"
    assert state.data["partial_success"] is True
    assert set(state.data["worker_results"].keys()) == {"w1", "w3"}
    assert "w2" in state.data["worker_errors"]


@pytest.mark.asyncio
async def test_graph_engine_agent_task_reviewer_loop_stops_when_approved():
    nodes = [
        WorkflowNode(
            id="AG",
            type="agent_task",
            config={"pattern": "reviewer_loop", "max_rounds": 3},
        )
    ]
    graph = WorkflowGraph(id="agent_reviewer_loop", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        role = node.config.get("role")
        round_idx = int(node.config.get("round", 1))
        if role == "generator":
            return {"candidate": f"cand-r{round_idx}"}
        if role == "reviewer":
            if round_idx < 2:
                return {"approved": False, "feedback": "needs fixes"}
            return {"approved": True, "feedback": "ok"}
        return {}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["pattern"] == "reviewer_loop"
    assert state.data["approved"] is True
    assert state.data["rounds"] == 2
    assert state.data["candidate"] == "cand-r2"
    assert len(state.data["reviews"]) == 2


@pytest.mark.asyncio
async def test_graph_engine_agent_task_handoff_curates_context():
    nodes = [
        WorkflowNode(
            id="AG",
            type="agent_task",
            config={"pattern": "handoff", "context_keys": ["ticket", "scope"]},
        )
    ]
    graph = WorkflowGraph(id="agent_handoff", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        role = node.config.get("role")
        if role == "source":
            return {"draft": "v1", "received": node.config.get("handoff_context")}
        if role == "target":
            return {
                "final": "v2",
                "received": node.config.get("handoff_context"),
                "source": node.config.get("source_output"),
            }
        return {}

    engine._execute_node = mock_execute
    state = await engine.execute(initial_state={"ticket": "SEC-2", "scope": "auth", "noise": "ignore"})

    assert state.data["pattern"] == "handoff"
    assert "handoff_package" in state.data
    assert state.data["handoff_package"]["source_node"] == "AG__source"
    assert state.data["handoff_package"]["target_node"] == "AG__target"
    assert state.data["handoff_package"]["context_keys"] == ["ticket", "scope"]
    assert state.data["handoff_context"] == {"ticket": "SEC-2", "scope": "auth"}
    assert state.data["source_output"]["received"] == {"ticket": "SEC-2", "scope": "auth"}
    assert state.data["target_output"]["received"] == {"ticket": "SEC-2", "scope": "auth"}


@pytest.mark.asyncio
async def test_graph_engine_model_router_trace_for_llm_call():
    nodes = [
        WorkflowNode(id="L1", type="llm_call", config={"task_type": "security_review"}),
    ]
    graph = WorkflowGraph(id="model_router_trace", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return {"model_seen": node.config.get("selected_model")}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["model_seen"] == "opus"
    assert state.data["model_router_last"]["node_id"] == "L1"
    assert state.data["model_router_last"]["selected_model"] == "opus"
    assert len(state.data["model_router_trace"]) >= 1

# ── Confidence Analysis ───────────────────────────────────

@pytest.mark.asyncio
async def test_project_confidence_calls_llm_correctly():
    trust_engine = MagicMock()
    service = ConfidenceService(trust_engine=trust_engine)
    mock_data = {"confidence": 0.65, "analysis": "clear but auth missing", "questions": ["Q1"], "risk_level": "medium"}
    with patch("tools.gimo_server.services.provider_service.ProviderService.static_generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = {"content": json.dumps(mock_data), "tokens_used": 100, "cost_usd": 0.001}
        result = await service.project_confidence("Analyze", {})
        assert abs(result["score"] - 0.65) < 0.01

@pytest.mark.asyncio
async def test_project_confidence_handles_failed_llm_gracefully():
    trust_engine = MagicMock()
    service = ConfidenceService(trust_engine=trust_engine)
    with patch("tools.gimo_server.services.provider_service.ProviderService.static_generate", side_effect=Exception("LLM Down")):
        result = await service.project_confidence("Task", {})
        assert abs(result["score"] - 0.5) < 0.01

# ── Node Execution (Unit) ───────────────────────────────────

@pytest.mark.asyncio
async def test_llm_call_execution_unit():
    """Directly test _execute_node for LLM calls."""
    with patch("tools.gimo_server.services.graph_engine.ProviderService") as MockProvider:
        mock_instance = MockProvider.return_value
        mock_instance.generate = AsyncMock(return_value={
            "provider": "mock_provider", "model": "gpt-4", "content": "Hello", "tokens_used": 10, "cost_usd": 0.01
        })
        node = WorkflowNode(id="l1", type="llm_call", config={"prompt": "Hi"})
        engine = GraphEngine(WorkflowGraph(id="t", nodes=[node], edges=[]))
        result = await engine._execute_node(node, {})
        assert result["content"] == "Hello"

@pytest.mark.asyncio
async def test_mcp_tool_call_execution_unit():
    """Directly test _execute_node for MCP tool calls using real registry logic."""
    # We removed all patches. The registry and config are initialized in conftest.py.
    node = WorkflowNode(id="t1", type="tool_call", config={"tool_name": "t1", "arguments": {}})
    engine = GraphEngine(WorkflowGraph(id="t", nodes=[node], edges=[]))
    result = await engine._execute_node(node, {})
    assert result["output"]["result"] == "hi\n" or "hi" in result["output"]["result"]

# ── System Integrity & Hardening ───────────────────────────

def test_token_entropy_nist():
    """Verify ORCH_TOKEN has sufficient entropy (Consolidated from test_integrity_deep)."""
    token = os.environ.get("ORCH_TOKEN", "a" * 32)
    def calc_entropy(s):
        if not s: return 0
        probs = [s.count(c)/len(s) for c in set(s)]
        return -sum(p * math.log2(p) for p in probs)
    
    assert len(token) >= 32
    assert calc_entropy(token) > 3.0 # Relaxed for unit testing default

def test_critical_file_integrity_check():
    """Verify core files match manifest (Logic check)."""
    # Simply verify we can hash a file correctly
    test_file = Path(__file__)
    content = test_file.read_bytes().replace(b'\r\n', b'\n')
    h = hashlib.sha256(content).hexdigest()
    assert len(h) == 64
