import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from tools.repo_orchestrator.services.plan_executor import PlanExecutor
from tools.repo_orchestrator.models import Plan, PlanTask, AgentAssignment, DelegationRequest


def make_plan(tasks, assignments=None):
    if assignments is None:
        all_ids = [t.id for t in tasks]
        assignments = [AgentAssignment(agentId="api", taskIds=all_ids)]
    return Plan(id="plan-1", title="Test Plan", status="approved", tasks=tasks, assignments=assignments)


def test_resolve_parallel_groups_linear():
    """Linear chain: A -> B -> C. 3 sequential groups."""
    tasks = [
        PlanTask(id="A", title="A", description="A", status="pending", dependencies=[]),
        PlanTask(id="B", title="B", description="B", status="pending", dependencies=["A"]),
        PlanTask(id="C", title="C", description="C", status="pending", dependencies=["B"]),
    ]
    groups = PlanExecutor.resolve_parallel_groups(tasks)
    assert len(groups) == 3
    assert groups[0][0].id == "A"
    assert groups[1][0].id == "B"
    assert groups[2][0].id == "C"


def test_resolve_parallel_groups_diamond():
    """Diamond: A -> B, A -> C, B+C -> D. 3 groups, middle has 2 parallel."""
    tasks = [
        PlanTask(id="A", title="A", description="A", status="pending", dependencies=[]),
        PlanTask(id="B", title="B", description="B", status="pending", dependencies=["A"]),
        PlanTask(id="C", title="C", description="C", status="pending", dependencies=["A"]),
        PlanTask(id="D", title="D", description="D", status="pending", dependencies=["B", "C"]),
    ]
    groups = PlanExecutor.resolve_parallel_groups(tasks)
    assert len(groups) == 3
    assert len(groups[0]) == 1  # A
    assert len(groups[1]) == 2  # B, C in parallel
    assert len(groups[2]) == 1  # D


def test_resolve_parallel_groups_all_independent():
    """All independent: all in one group."""
    tasks = [
        PlanTask(id="A", title="A", description="A", status="pending", dependencies=[]),
        PlanTask(id="B", title="B", description="B", status="pending", dependencies=[]),
        PlanTask(id="C", title="C", description="C", status="pending", dependencies=[]),
    ]
    groups = PlanExecutor.resolve_parallel_groups(tasks)
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_resolve_parallel_groups_empty():
    groups = PlanExecutor.resolve_parallel_groups([])
    assert groups == []


@pytest.fixture(autouse=True)
def mock_ws():
    mock_mgr = AsyncMock()
    mock_mgr.broadcast = AsyncMock()
    with patch("tools.repo_orchestrator.ws.manager.manager", mock_mgr):
        yield mock_mgr


@pytest.mark.asyncio
async def test_delegate_batch():
    mock_agent = MagicMock()
    mock_agent.id = "sub-1"

    with patch("tools.repo_orchestrator.services.sub_agent_manager.SubAgentManager.create_sub_agent", new_callable=AsyncMock, return_value=mock_agent), \
         patch("tools.repo_orchestrator.services.sub_agent_manager.SubAgentManager.execute_task", new_callable=AsyncMock, return_value="Result A"):

        requests = [
            DelegationRequest(subTaskDescription="Task A", modelPreference="llama3"),
            DelegationRequest(subTaskDescription="Task B", modelPreference="codellama"),
        ]
        results = await PlanExecutor.delegate_batch("parent-1", requests)

    assert len(results) == 2
    assert all(r["status"] == "completed" for r in results)


@pytest.mark.asyncio
async def test_execute_single_task_injects_plan_scope_system_prompt():
    task = PlanTask(id="T1", title="Auth", description="Implement auth", status="pending", dependencies=[])
    plan = make_plan([task], assignments=[AgentAssignment(agentId="agent-1", taskIds=["T1"])])

    manager = MagicMock()
    manager.create_sub_agent = AsyncMock(return_value=MagicMock(id="sub-1"))
    manager.execute_task = AsyncMock(return_value="ok")

    result = await PlanExecutor._execute_single_task(plan, task, manager)

    assert result == "ok"
    manager.create_sub_agent.assert_awaited_once()
    req = manager.create_sub_agent.await_args.args[1]
    assert isinstance(req, DelegationRequest)
    assert "system_prompt" in req.constraints
    assert "Plan=plan-1" in req.constraints["system_prompt"]
    assert "Task=T1" in req.constraints["system_prompt"]
