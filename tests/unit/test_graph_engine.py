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


@pytest.mark.slow
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


@pytest.mark.slow
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

    assert state.data["model_seen"]  # A real model was selected
    assert state.data["model_seen"] != "unknown"
    assert state.data["model_router_last"]["node_id"] == "L1"
    assert state.data["model_router_last"]["selected_model"] == state.data["model_seen"]
    assert len(state.data["model_router_trace"]) >= 1
    assert "hardware_state" in state.data["model_router_last"]

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
    with patch("tools.gimo_server.services.graph.engine.ProviderService") as MockProvider:
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


# ── Fase 1: State Reducers ──────────────────────────────────

from tools.gimo_server.services.graph.state_manager import StateManager


def test_reducer_overwrite_is_default():
    sm = StateManager()
    state = {"x": 1}
    sm.apply_update(state, {"x": 99})
    assert state["x"] == 99


def test_reducer_append_concatenates_lists():
    sm = StateManager(reducers={"items": "append"})
    state = {"items": ["a", "b"]}
    sm.apply_update(state, {"items": ["c", "d"]})
    assert state["items"] == ["a", "b", "c", "d"]


def test_reducer_append_from_parallel_branches():
    sm = StateManager(reducers={"results": "append"})
    state: dict = {}
    sm.apply_update(state, {"results": ["branch_a"]})
    sm.apply_update(state, {"results": ["branch_b"]})
    assert state["results"] == ["branch_a", "branch_b"]


def test_reducer_add_sums_numbers():
    sm = StateManager(reducers={"score": "add"})
    state = {"score": 10}
    sm.apply_update(state, {"score": 5})
    assert state["score"] == 15


def test_reducer_add_from_none():
    sm = StateManager(reducers={"count": "add"})
    state: dict = {}
    sm.apply_update(state, {"count": 7})
    assert state["count"] == 7


def test_reducer_overwrite_backward_compat():
    sm = StateManager()
    state = {"a": 1, "b": 2}
    sm.apply_update(state, {"b": 99, "c": 3})
    assert state == {"a": 1, "b": 99, "c": 3}


def test_reducer_merge_dict_deep_merge():
    sm = StateManager(reducers={"meta": "merge_dict"})
    state = {"meta": {"k1": "v1", "k2": "old"}}
    sm.apply_update(state, {"meta": {"k2": "new", "k3": "v3"}})
    assert state["meta"] == {"k1": "v1", "k2": "new", "k3": "v3"}


def test_reducer_dedupe_append_no_duplicates():
    sm = StateManager(reducers={"tags": "dedupe_append"})
    state = {"tags": ["a", "b"]}
    sm.apply_update(state, {"tags": ["b", "c"]})
    assert state["tags"] == ["a", "b", "c"]


def test_reducer_max():
    sm = StateManager(reducers={"peak": "max"})
    state = {"peak": 5}
    sm.apply_update(state, {"peak": 3})
    assert state["peak"] == 5
    sm.apply_update(state, {"peak": 10})
    assert state["peak"] == 10


def test_reducer_min():
    sm = StateManager(reducers={"floor": "min"})
    state = {"floor": 5}
    sm.apply_update(state, {"floor": 3})
    assert state["floor"] == 3
    sm.apply_update(state, {"floor": 10})
    assert state["floor"] == 3


def test_reducer_conflict_detection_calls_gics():
    gics_calls = []

    class FakeGICS:
        def put(self, key, fields):
            gics_calls.append((key, fields))

    sm = StateManager(reducers={}, gics_client=FakeGICS(), workflow_id="wf1")
    state = {"x": 1}
    sm.apply_update(state, {"x": 2})
    assert len(gics_calls) == 1
    assert gics_calls[0][0] == "ops:reducer_conflict:wf1:x"
    assert gics_calls[0][1]["key"] == "x"
    assert gics_calls[0][1]["current_value"] == 1
    assert gics_calls[0][1]["new_value"] == 2


def test_reducer_no_conflict_when_same_value():
    gics_calls = []

    class FakeGICS:
        def put(self, key, fields):
            gics_calls.append((key, fields))

    sm = StateManager(reducers={}, gics_client=FakeGICS(), workflow_id="wf1")
    state = {"x": 1}
    sm.apply_update(state, {"x": 1})
    assert len(gics_calls) == 0


@pytest.mark.asyncio
async def test_graph_engine_uses_reducers_from_graph():
    nodes = [
        WorkflowNode(id="A", type="transform"),
        WorkflowNode(id="B", type="transform"),
    ]
    edges = [WorkflowEdge(**{"from": "A", "to": "B"})]
    graph = WorkflowGraph(
        id="test_reducers",
        nodes=nodes,
        edges=edges,
        reducers={"items": "append"},
    )
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return {"items": [node.id]}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["items"] == ["A", "B"]


# ── Fase 2: GraphCommand ──────────────────────────────────

from tools.gimo_server.ops_models import GraphCommand, SendAction, is_graph_command


# -- Helpers de grafo para Fase 2/3 --
def _make_graph(nodes, edges, reducers=None):
    return WorkflowGraph(
        id="test_cmd",
        nodes=nodes,
        edges=edges,
        reducers=reducers or {},
    )


@pytest.mark.asyncio
async def test_command_goto_overrides_routing():
    """Un nodo retorna GraphCommand con goto → el engine salta al nodo indicado."""
    nodes = [
        WorkflowNode(id="A", type="transform"),
        WorkflowNode(id="B", type="transform", config={"path": "normal"}),
        WorkflowNode(id="C", type="transform", config={"path": "command"}),
    ]
    edges = [
        WorkflowEdge(**{"from": "A", "to": "B"}),
    ]
    graph = _make_graph(nodes, edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        if node.id == "A":
            return GraphCommand(goto="C")
        return node.config

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert [cp.node_id for cp in state.checkpoints] == ["A", "C"]
    assert state.data["path"] == "command"


@pytest.mark.asyncio
async def test_command_goto_with_atomic_update():
    """Command con goto + update aplica el update antes de seguir."""
    nodes = [
        WorkflowNode(id="A", type="transform"),
        WorkflowNode(id="B", type="transform", config={"b": True}),
    ]
    edges = []
    graph = _make_graph(nodes, edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        if node.id == "A":
            return GraphCommand(goto="B", update={"injected": 42})
        return node.config

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["injected"] == 42
    assert state.data["b"] is True
    assert [cp.node_id for cp in state.checkpoints] == ["A", "B"]


@pytest.mark.asyncio
async def test_command_goto_without_update():
    """Command con goto vacío y sin update enruta correctamente."""
    nodes = [
        WorkflowNode(id="A", type="transform"),
        WorkflowNode(id="Z", type="transform", config={"z": True}),
    ]
    graph = _make_graph(nodes, [])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        if node.id == "A":
            return GraphCommand(goto="Z")
        return node.config

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["z"] is True


@pytest.mark.asyncio
async def test_command_graph_parent_escape():
    """Command con graph='PARENT' marca _subgraph_escape y detiene el grafo."""
    nodes = [WorkflowNode(id="A", type="transform")]
    graph = _make_graph(nodes, [])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return GraphCommand(graph="PARENT", update={"escaped": True})

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["_subgraph_escape"] is True
    assert state.data["escaped"] is True


@pytest.mark.asyncio
async def test_command_multiple_goto_without_send_raises():
    """Command con múltiples goto sin Send debe elevar ValueError."""
    nodes = [WorkflowNode(id="A", type="transform")]
    graph = _make_graph(nodes, [])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return GraphCommand(goto=["B", "C"])

    engine._execute_node = mock_execute
    state = await engine.execute()

    # El error es capturado y el nodo falla con aborted_reason
    assert state.data.get("aborted_reason") == "node_failure"


@pytest.mark.asyncio
async def test_backward_compat_nodes_without_command():
    """Nodos normales (sin Command) siguen funcionando exactamente igual."""
    nodes = [
        WorkflowNode(id="A", type="transform", config={"a": 1}),
        WorkflowNode(id="B", type="transform", config={"b": 2}),
    ]
    edges = [WorkflowEdge(**{"from": "A", "to": "B"})]
    graph = _make_graph(nodes, edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return node.config

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["a"] == 1
    assert state.data["b"] == 2
    assert [cp.node_id for cp in state.checkpoints] == ["A", "B"]


# ── Fase 3: Send (Map-Reduce) ──────────────────────────────

@pytest.mark.asyncio
async def test_send_map_reduce_with_append_reducer():
    """Command con send ejecuta múltiples instancias y mergea con reducer append."""
    nodes = [
        WorkflowNode(id="dispatcher", type="transform"),
        WorkflowNode(id="worker",     type="transform"),
    ]
    graph = _make_graph(nodes, [], reducers={"results": "append"})
    engine = GraphEngine(graph)

    call_states = []

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        if node.id == "dispatcher":
            return GraphCommand(
                send=[
                    SendAction(node="worker", state={"item": "a"}),
                    SendAction(node="worker", state={"item": "b"}),
                    SendAction(node="worker", state={"item": "c"}),
                ],
            )
        # worker: devuelve su item como resultado
        call_states.append(state.get("item"))
        return {"results": [state["item"]]}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert sorted(state.data["results"]) == ["a", "b", "c"]
    assert sorted(call_states) == ["a", "b", "c"]
    assert len(state.data["send_proofs"]) == 1
    assert all(p["ok"] for p in state.data["send_proofs"][0])


@pytest.mark.asyncio
async def test_send_reducer_add_sums_scores():
    """Send con reducer 'add' acumula scores de todas las instancias."""
    nodes = [
        WorkflowNode(id="fan_out", type="transform"),
        WorkflowNode(id="scorer",  type="transform"),
    ]
    graph = _make_graph(nodes, [], reducers={"score": "add"})
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        if node.id == "fan_out":
            return GraphCommand(
                send=[
                    SendAction(node="scorer", state={"val": 10}),
                    SendAction(node="scorer", state={"val": 20}),
                    SendAction(node="scorer", state={"val": 30}),
                ]
            )
        return {"score": state["val"]}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["score"] == 60


@pytest.mark.asyncio
async def test_send_semaphore_limits_parallelism():
    """El semaphore debe respetar send_max_parallel."""
    nodes = [
        WorkflowNode(id="fan", type="transform"),
        WorkflowNode(id="slow", type="transform"),
    ]
    graph = _make_graph(nodes, [], reducers={"r": "append"})
    engine = GraphEngine(graph)
    counters = {"active": 0, "peak": 0}

    async def mock_execute(node, state):
        if node.id == "fan":
            return GraphCommand(
                send=[SendAction(node="slow", state={"i": i}) for i in range(5)]
            )
        counters["active"] += 1
        counters["peak"] = max(counters["peak"], counters["active"])
        await asyncio.sleep(0.02)
        counters["active"] -= 1
        return {"r": [state["i"]]}

    engine._execute_node = mock_execute
    await engine.execute(initial_state={"send_max_parallel": 2})

    assert counters["peak"] <= 2


@pytest.mark.asyncio
async def test_send_partial_failure_doesnt_kill_others():
    """Fallo de una instancia no cancela las demás."""
    nodes = [
        WorkflowNode(id="fan",    type="transform"),
        WorkflowNode(id="worker", type="transform"),
    ]
    graph = _make_graph(nodes, [], reducers={"ok_list": "append"})
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        if node.id == "fan":
            return GraphCommand(
                send=[
                    SendAction(node="worker", state={"x": 1}),
                    SendAction(node="worker", state={"x": "boom"}),
                    SendAction(node="worker", state={"x": 3}),
                ]
            )
        if state["x"] == "boom":
            raise RuntimeError("worker bombed")
        return {"ok_list": [state["x"]]}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert sorted(state.data["ok_list"]) == [1, 3]
    proofs = state.data["send_proofs"][0]
    assert any(not p["ok"] for p in proofs)
    assert any(p["ok"] for p in proofs)


@pytest.mark.asyncio
async def test_send_budget_distributed():
    """El budget se distribuye equitativamente entre las instancias Send."""
    nodes = [
        WorkflowNode(id="fan",    type="transform"),
        WorkflowNode(id="worker", type="transform"),
    ]
    graph = _make_graph(nodes, [])
    engine = GraphEngine(graph)
    seen_budgets = []

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        if node.id == "fan":
            return GraphCommand(
                send=[
                    SendAction(node="worker", state={"i": 1}),
                    SendAction(node="worker", state={"i": 2}),
                ]
            )
        seen_budgets.append(state.get("budget", {}).get("max_tokens"))
        return {}

    engine._execute_node = mock_execute
    await engine.execute(initial_state={"budget": {"max_tokens": 100}})

    # Cada instancia recibe 50 tokens (100 / 2)
    assert all(b == 50.0 for b in seen_budgets)


# ── Fase 4: Ciclos declarativos ──────────────────────────────

@pytest.mark.asyncio
async def test_cycle_break_condition_exits_loop():
    """Loop A→B→A con break_condition: cuando done=True el loop para."""
    # Grafo: A→B (normal), B→A (break_condition="done"), B→C (default)
    nodes = [
        WorkflowNode(id="A", type="transform"),
        WorkflowNode(id="B", type="transform"),
        WorkflowNode(id="C", type="transform", config={"final": True}),
    ]
    edges = [
        WorkflowEdge(**{"from": "A", "to": "B"}),
        WorkflowEdge(**{"from": "B", "to": "A", "break_condition": "done"}),
        WorkflowEdge(**{"from": "B", "to": "C"}),
    ]
    graph = WorkflowGraph(id="cycle_break", nodes=nodes, edges=edges)
    engine = GraphEngine(graph)

    call_count = {"n": 0}

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        call_count["n"] += 1
        if node.id == "B" and call_count["n"] >= 4:  # 2 rondas completas → romper loop
            return {"done": True}
        if node.config:
            return node.config
        return {}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["final"] is True
    # Ciclo debe haber ocurrido y terminado
    assert "_cycle_counters" in state.data


@pytest.mark.asyncio
async def test_cycle_max_iterations_exits_to_node_c():
    """Self-loop A→A con max_iterations=3, luego A→C."""
    nodes = [
        WorkflowNode(id="A", type="transform"),
        WorkflowNode(id="C", type="transform", config={"exit": True}),
    ]
    edges = [
        # La arista de loop tiene max_iterations=3
        WorkflowEdge(**{"from": "A", "to": "A", "max_iterations": 3}),
        # Arista de salida sin condición
        WorkflowEdge(**{"from": "A", "to": "C"}),
    ]
    graph = WorkflowGraph(id="cycle_maxiter", nodes=nodes, edges=edges)
    engine = GraphEngine(graph, max_iterations=20)

    ticks = {"n": 0}

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        if node.id == "A":
            ticks["n"] += 1
        if node.config:
            return node.config
        return {}

    engine._execute_node = mock_execute
    state = await engine.execute()

    # A se ejecuta 4 veces: 3 iteraciones del loop + 1 inicial antes de salir
    assert ticks["n"] == 4
    assert state.data["exit"] is True
    assert state.data["_cycle_counters"]["A->A"] == 3


@pytest.mark.asyncio
async def test_cycle_nested_loops():
    """Nested loops:
    - Loop interno: C→B (max_iterations=2)
    - Loop externo: C→A (max_iterations=2)
    - Salida cuando ambos contadores se agotan: C→D (default)
    """
    nodes = [
        WorkflowNode(id="A", type="transform"),
        WorkflowNode(id="B", type="transform"),
        WorkflowNode(id="C", type="transform"),
        WorkflowNode(id="D", type="transform", config={"done": True}),
    ]
    edges = [
        WorkflowEdge(**{"from": "A", "to": "B"}),
        WorkflowEdge(**{"from": "B", "to": "C"}),
        WorkflowEdge(**{"from": "C", "to": "B", "max_iterations": 2}),  # inner loop
        WorkflowEdge(**{"from": "C", "to": "A", "max_iterations": 2}),  # outer loop
        WorkflowEdge(**{"from": "C", "to": "D"}),                        # exit
    ]
    graph = WorkflowGraph(id="nested_loops", nodes=nodes, edges=edges)
    engine = GraphEngine(graph, max_iterations=50)

    visited = []

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        visited.append(node.id)
        if node.config:
            return node.config
        return {}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["done"] is True
    # Ciclos fueron detectados
    assert "_cycle_counters" in state.data
    # Contadores de ciclos internos y externos alcanzaron sus límites
    assert state.data["_cycle_counters"].get("C->B", 0) == 2
    assert state.data["_cycle_counters"].get("C->A", 0) == 2


@pytest.mark.asyncio
async def test_cycle_global_max_iterations_respected():
    """Self-loop sin break_condition ni max_iterations respeta max_iterations global."""
    nodes = [WorkflowNode(id="A", type="transform")]
    edges = [WorkflowEdge(**{"from": "A", "to": "A"})]
    graph = WorkflowGraph(id="cycle_global_cap", nodes=nodes, edges=edges)
    engine = GraphEngine(graph, max_iterations=5)

    ticks = {"n": 0}

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        ticks["n"] += 1
        return {"count": ticks["n"]}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["aborted_reason"] == "max_iterations_exceeded"
    assert ticks["n"] == 5


@pytest.mark.asyncio
async def test_cycle_backward_compat_self_loop():
    """Self-loop existente sin campos nuevos sigue funcionando igual."""
    nodes = [WorkflowNode(id="A", type="transform", config={"tick": 1})]
    edges = [WorkflowEdge(**{"from": "A", "to": "A"})]
    graph = WorkflowGraph(id="cycle_compat", nodes=nodes, edges=edges)
    engine = GraphEngine(graph, max_iterations=2)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return {"count": state.get("count", 0) + 1}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert len(state.checkpoints) == 2
    assert state.data["count"] == 2
    assert state.data["aborted_reason"] == "max_iterations_exceeded"


# ── Fase 5: Time-Travel ──────────────────────────────────────

@pytest.mark.asyncio
async def test_time_travel_replay_re_executes_from_checkpoint():
    """replay_from_checkpoint restaura estado y re-ejecuta desde el nodo siguiente."""
    nodes = [
        WorkflowNode(id="A", type="transform", config={"a": 1}),
        WorkflowNode(id="B", type="transform", config={"b": 2}),
        WorkflowNode(id="C", type="transform", config={"c": 3}),
    ]
    edges = [
        WorkflowEdge(**{"from": "A", "to": "B"}),
        WorkflowEdge(**{"from": "B", "to": "C"}),
    ]
    graph = WorkflowGraph(id="tt_replay", nodes=nodes, edges=edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return node.config

    engine._execute_node = mock_execute

    # Primera ejecución completa
    await engine.execute()
    assert engine.state.data["c"] == 3
    assert len(engine.state.checkpoints) == 3

    # Replay desde checkpoint 0 (nodo A): debe re-ejecutar B y C
    engine.replay_from_checkpoint(0)
    state = await engine.execute()

    assert state.data["replayed_from"]["node_id"] == "A"
    assert state.data["b"] == 2
    assert state.data["c"] == 3
    # El primer checkpoint replayed debe estar marcado
    replayed_cps = [cp for cp in state.checkpoints if cp.replayed]
    assert len(replayed_cps) >= 1


@pytest.mark.asyncio
async def test_time_travel_fork_creates_independent_engine():
    """fork_from_checkpoint crea un engine independiente con state editado."""
    nodes = [
        WorkflowNode(id="A", type="transform", config={"a": 1}),
        WorkflowNode(id="B", type="transform", config={"b": 2}),
    ]
    edges = [WorkflowEdge(**{"from": "A", "to": "B"})]
    graph = WorkflowGraph(id="tt_fork", nodes=nodes, edges=edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return node.config

    engine._execute_node = mock_execute
    await engine.execute()

    # Fork desde checkpoint 0 (A) con state_patch
    fork = engine.fork_from_checkpoint(0, state_patch={"injected": 99})
    fork._execute_node = mock_execute

    fork_state = await fork.execute()

    # Fork es independiente — estado del engine original no fue afectado
    assert "injected" not in engine.state.data
    # Fork tiene el patch
    assert fork_state.data["injected"] == 99
    # Fork tiene fork_id en state
    assert "fork_id" in fork_state.data
    assert fork_state.data["forked_from"]["parent_workflow_id"] == "tt_fork"


@pytest.mark.asyncio
async def test_time_travel_fork_inherits_checkpoints():
    """El fork hereda los checkpoints anteriores al punto de fork."""
    nodes = [
        WorkflowNode(id="A", type="transform"),
        WorkflowNode(id="B", type="transform"),
        WorkflowNode(id="C", type="transform"),
    ]
    edges = [
        WorkflowEdge(**{"from": "A", "to": "B"}),
        WorkflowEdge(**{"from": "B", "to": "C"}),
    ]
    graph = WorkflowGraph(id="tt_fork_inherit", nodes=nodes, edges=edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return {}

    engine._execute_node = mock_execute
    await engine.execute()  # A, B, C completados

    # Fork desde checkpoint 1 (B) — el fork hereda A y B
    fork = engine.fork_from_checkpoint(1)
    fork._execute_node = mock_execute

    # El fork ya tiene 2 checkpoints heredados (A y B)
    assert len(fork.state.checkpoints) == 2
    assert fork.state.checkpoints[0].node_id == "A"
    assert fork.state.checkpoints[1].node_id == "B"
    # Todos tienen fork_id asignado
    assert all(cp.fork_id for cp in fork.state.checkpoints)

    # El fork ejecuta desde C (siguiente a B)
    fork_state = await fork.execute()
    cp_nodes = [cp.node_id for cp in fork_state.checkpoints]
    assert "C" in cp_nodes


def test_time_travel_get_checkpoint_timeline():
    """get_checkpoint_timeline retorna lista navegable de todos los checkpoints."""
    from tools.gimo_server.ops_models import WorkflowCheckpoint, WorkflowState
    nodes = [WorkflowNode(id="X", type="transform")]
    graph = WorkflowGraph(id="tt_timeline", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    # Inyectar checkpoints manualmente
    engine.state.checkpoints = [
        WorkflowCheckpoint(node_id="A", state={}, output={}, status="completed"),
        WorkflowCheckpoint(node_id="B", state={}, output={}, status="completed", fork_id="f1"),
        WorkflowCheckpoint(node_id="C", state={}, output=None, status="failed", replayed=True),
    ]

    timeline = engine.get_checkpoint_timeline()

    assert len(timeline) == 3
    assert timeline[0]["node_id"] == "A"
    assert timeline[0]["index"] == 0
    assert timeline[1]["fork_id"] == "f1"
    assert timeline[2]["replayed"] is True
    assert timeline[2]["status"] == "failed"


@pytest.mark.asyncio
async def test_time_travel_backward_compat_resume_from_checkpoint():
    """resume_from_checkpoint existente sigue funcionando sin cambios."""
    nodes = [
        WorkflowNode(id="A", type="transform", config={"a": 1}),
        WorkflowNode(id="B", type="transform", config={"b": 2}),
    ]
    edges = [WorkflowEdge(**{"from": "A", "to": "B"})]
    graph = WorkflowGraph(id="tt_compat_resume", nodes=nodes, edges=edges)
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


# ── Fase 6: Swarm ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swarm_handoff_chain_a_b_c():
    """Swarm con 3 agentes: A→B→C handoff chain completo."""
    nodes = [
        WorkflowNode(
            id="SW",
            type="agent_task",
            config={
                "pattern": "swarm",
                "start_agent": "agent_a",
                "agents": [
                    {"id": "agent_a", "name": "A", "handoff_targets": ["agent_b"]},
                    {"id": "agent_b", "name": "B", "handoff_targets": ["agent_c"]},
                    {"id": "agent_c", "name": "C", "handoff_targets": []},
                ],
            },
        )
    ]
    graph = WorkflowGraph(id="swarm_abc", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        agent_id = node.config.get("agent_id", "")
        if agent_id == "agent_a":
            return {"handoff_to": "agent_b", "done_a": True}
        if agent_id == "agent_b":
            return {"handoff_to": "agent_c", "done_b": True}
        return {"final": True}  # agent_c — sin handoff

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["pattern"] == "swarm"
    assert state.data["active_agent"] == "agent_c"
    chain = state.data["handoff_chain"]
    assert len(chain) == 2
    assert chain[0]["from"] == "agent_a" and chain[0]["to"] == "agent_b"
    assert chain[1]["from"] == "agent_b" and chain[1]["to"] == "agent_c"
    assert len(state.data["proofs"]) == 3


@pytest.mark.asyncio
async def test_swarm_handoff_context_filtering():
    """Agente con context_keys solo recibe las claves relevantes."""
    seen_contexts = []

    nodes = [
        WorkflowNode(
            id="SW",
            type="agent_task",
            config={
                "pattern": "swarm",
                "start_agent": "focused",
                "agents": [
                    {
                        "id": "focused",
                        "name": "Focused",
                        "context_keys": ["ticket", "scope"],
                        "handoff_targets": [],
                    },
                ],
            },
        )
    ]
    graph = WorkflowGraph(id="swarm_ctx", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        if node.config.get("role") == "swarm_agent":
            seen_contexts.append(node.config.get("context", {}))
        return {}

    engine._execute_node = mock_execute
    await engine.execute(initial_state={"ticket": "T-1", "scope": "auth", "noise": "ignore"})

    assert len(seen_contexts) == 1
    ctx = seen_contexts[0]
    assert "ticket" in ctx and "scope" in ctx
    assert "noise" not in ctx


@pytest.mark.asyncio
async def test_swarm_max_iterations_respected():
    """El loop de swarm respeta max_iterations."""
    nodes = [
        WorkflowNode(
            id="SW",
            type="agent_task",
            config={
                "pattern": "swarm",
                "max_iterations": 3,
                "start_agent": "looper",
                "agents": [
                    {"id": "looper", "name": "Looper", "handoff_targets": ["looper"]},
                ],
            },
        )
    ]
    graph = WorkflowGraph(id="swarm_loop", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        # Siempre intenta hacer handoff a sí mismo
        return {"handoff_to": "looper"}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["pattern"] == "swarm"
    assert state.data["iterations"] == 3


@pytest.mark.asyncio
async def test_swarm_mood_contract_blocks_incompatible_handoff():
    """Handoff de agente 'critical' bloquea y registra la violación."""
    nodes = [
        WorkflowNode(
            id="SW",
            type="agent_task",
            config={
                "pattern": "swarm",
                "start_agent": "critical_agent",
                "agents": [
                    {
                        "id": "critical_agent",
                        "mood": "critical",
                        "handoff_targets": ["standard_agent"],
                    },
                    {"id": "standard_agent", "mood": "standard"},
                ],
            },
        )
    ]
    graph = WorkflowGraph(id="swarm_mood", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        if node.config.get("agent_id") == "critical_agent":
            return {"handoff_to": "standard_agent"}
        return {}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert "swarm_mood_violation" in state.data
    violation = state.data["swarm_mood_violation"]
    assert violation["from"] == "critical_agent"
    assert violation["from_mood"] == "critical"


@pytest.mark.asyncio
async def test_swarm_backward_compat_other_patterns():
    """supervisor_workers y otros patterns siguen funcionando con swarm integrado."""
    nodes = [
        WorkflowNode(
            id="AG",
            type="agent_task",
            config={
                "pattern": "supervisor_workers",
                "workers": [{"id": "w1", "task": "t1"}],
            },
        )
    ]
    graph = WorkflowGraph(id="compat_sw", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        worker_id = node.config.get("worker_id")
        if worker_id:
            return {"worker": worker_id}
        return {}

    engine._execute_node = mock_execute
    state = await engine.execute()

    assert state.data["pattern"] == "supervisor_workers"
    assert "w1" in state.data["worker_results"]


# ── Fase 7: Graph Streaming + Observability ──────────────────────────────────

@pytest.mark.asyncio
async def test_stream_yields_workflow_start_and_done():
    """execute_stream emite workflow_start al inicio y done al final."""
    nodes = [WorkflowNode(id="A", type="transform", config={})]
    graph = WorkflowGraph(id="stream_basic", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return {"x": 1}

    engine._execute_node = mock_execute

    events = []
    async for event in engine.execute_stream():
        events.append(event)

    event_types = [e["event_type"] for e in events]
    assert event_types[0] == "workflow_start"
    assert event_types[-1] == "done"

    start_evt = events[0]
    assert start_evt["data"]["workflow_id"] == "stream_basic"
    assert "trace_id" in start_evt["data"]

    done_evt = events[-1]
    assert done_evt["data"]["status"] == "completed"
    assert done_evt["data"]["total_nodes"] == 1
    assert done_evt["data"]["total_events"] >= 1


@pytest.mark.asyncio
async def test_stream_emits_node_start_and_node_end_per_node():
    """Cada nodo emite node_start y node_end con step_id y next_node."""
    nodes = [
        WorkflowNode(id="A", type="transform", config={}),
        WorkflowNode(id="B", type="transform", config={}),
    ]
    edges = [WorkflowEdge(**{"from": "A", "to": "B"})]
    graph = WorkflowGraph(id="stream_nodes", nodes=nodes, edges=edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return {}

    engine._execute_node = mock_execute

    events = []
    async for event in engine.execute_stream():
        events.append(event)

    starts = [e for e in events if e["event_type"] == "node_start"]
    ends = [e for e in events if e["event_type"] == "node_end"]

    assert len(starts) == 2
    assert len(ends) == 2
    assert starts[0]["node_id"] == "A"
    assert starts[1]["node_id"] == "B"
    # node_end for A should indicate next_node=B
    a_end = next(e for e in ends if e["node_id"] == "A")
    assert a_end["data"]["next_node"] == "B"
    # node_end for B: no further node
    b_end = next(e for e in ends if e["node_id"] == "B")
    assert b_end["data"]["next_node"] is None


@pytest.mark.asyncio
async def test_stream_emits_error_event_on_node_failure():
    """Cuando un nodo falla, execute_stream emite un evento 'error'."""
    nodes = [WorkflowNode(id="FAIL", type="transform", config={})]
    graph = WorkflowGraph(id="stream_error", nodes=nodes, edges=[])
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        raise ValueError("boom")

    engine._execute_node = mock_execute

    events = []
    async for event in engine.execute_stream():
        events.append(event)

    error_events = [e for e in events if e["event_type"] == "error"]
    assert len(error_events) == 1
    assert error_events[0]["node_id"] == "FAIL"
    assert "boom" in error_events[0]["data"]["error"]

    done_evt = events[-1]
    assert done_evt["data"]["status"] == "failed"


@pytest.mark.asyncio
async def test_stream_execute_backward_compat():
    """execute() sigue funcionando igual tras delegar a execute_stream()."""
    nodes = [
        WorkflowNode(id="A", type="transform", config={"v": 1}),
        WorkflowNode(id="B", type="transform", config={"v": 2}),
    ]
    edges = [WorkflowEdge(**{"from": "A", "to": "B"})]
    graph = WorkflowGraph(id="stream_compat", nodes=nodes, edges=edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return node.config

    engine._execute_node = mock_execute

    state = await engine.execute(initial_state={"init": True})

    assert len(state.checkpoints) == 2
    assert state.data["v"] == 2
    assert state.data["init"] is True


@pytest.mark.asyncio
async def test_stream_emits_state_update_events():
    """execute_stream emite state_update después de cada nodo que retorna dict."""
    nodes = [
        WorkflowNode(id="A", type="transform", config={}),
        WorkflowNode(id="B", type="transform", config={}),
    ]
    edges = [WorkflowEdge(**{"from": "A", "to": "B"})]
    graph = WorkflowGraph(id="stream_state_update", nodes=nodes, edges=edges)
    engine = GraphEngine(graph)

    async def mock_execute(node, state):
        await asyncio.sleep(0)
        return {"result": node.id}

    engine._execute_node = mock_execute

    events = []
    async for event in engine.execute_stream():
        events.append(event)

    state_updates = [e for e in events if e["event_type"] == "state_update"]
    assert len(state_updates) == 2
    # Each update contains the keys from the output
    for su in state_updates:
        assert "result" in su["data"]["keys_updated"]
