import pytest
from unittest.mock import patch, AsyncMock
from tools.repo_orchestrator.services.sub_agent_manager import SubAgentManager
from tools.repo_orchestrator.models import DelegationRequest


@pytest.fixture(autouse=True)
def mock_ws_manager():
    mock_mgr = AsyncMock()
    mock_mgr.broadcast = AsyncMock()
    with patch("tools.repo_orchestrator.ws.manager.manager", mock_mgr):
        yield mock_mgr


@pytest.fixture(autouse=True)
def clear_agents():
    SubAgentManager._sub_agents.clear()
    SubAgentManager._system_prompts.clear()
    yield
    SubAgentManager._sub_agents.clear()
    SubAgentManager._system_prompts.clear()


@pytest.fixture
def mock_model_service():
    with patch('tools.repo_orchestrator.services.sub_agent_manager.ModelService') as mock:
        mock.is_backend_ready = AsyncMock(return_value=True)
        mock.generate = AsyncMock(return_value="Mocked Response")
        yield mock


@pytest.mark.asyncio
async def test_create_sub_agent():
    req = DelegationRequest(subTaskDescription="Test task", modelPreference="llama3")
    agent = await SubAgentManager.create_sub_agent("parent-123", req)

    assert agent.parentId == "parent-123"
    assert agent.model == "llama3"
    assert agent.status == "starting"
    assert agent.id in SubAgentManager._sub_agents


@pytest.mark.asyncio
async def test_get_sub_agents():
    req = DelegationRequest(subTaskDescription="Test task", modelPreference="llama3")
    await SubAgentManager.create_sub_agent("parent-A", req)
    await SubAgentManager.create_sub_agent("parent-A", req)
    await SubAgentManager.create_sub_agent("parent-B", req)

    agents_a = SubAgentManager.get_sub_agents("parent-A")
    assert len(agents_a) == 2

    agents_all = SubAgentManager.get_sub_agents()
    assert len(agents_all) == 3


@pytest.mark.asyncio
async def test_terminate_sub_agent():
    req = DelegationRequest(subTaskDescription="Test task", modelPreference="llama3")
    agent = await SubAgentManager.create_sub_agent("parent-123", req)

    await SubAgentManager.terminate_sub_agent(agent.id)
    assert agent.status == "terminated"


@pytest.mark.asyncio
async def test_execute_task(mock_model_service):
    req = DelegationRequest(subTaskDescription="Test task", modelPreference="llama3")
    agent = await SubAgentManager.create_sub_agent("parent-123", req)

    response = await SubAgentManager.execute_task(agent.id, "Do something")

    assert response == "Mocked Response"
    assert agent.status == "idle"
    mock_model_service.generate.assert_called_once()
    call_args = mock_model_service.generate.call_args
    assert "# EJECUCIÓN" in call_args.args[0]
    assert call_args.kwargs.get("system_prompt")


@pytest.mark.asyncio
async def test_create_sub_agent_stores_master_system_prompt():
    req = DelegationRequest(
        subTaskDescription="Implement parser",
        modelPreference="llama3",
        constraints={"system_prompt": "Debes reportar blockers explícitamente."},
    )
    agent = await SubAgentManager.create_sub_agent("parent-xyz", req)

    prompt = SubAgentManager._system_prompts.get(agent.id)
    assert prompt is not None
    assert "Reglas obligatorias" in prompt
    assert "parent_agent=parent-xyz" in prompt
    assert "Implement parser" in prompt
    assert "Debes reportar blockers explícitamente." in prompt
