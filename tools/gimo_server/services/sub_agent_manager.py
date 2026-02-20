import uuid
import logging
from typing import Dict, List, Optional
from tools.gimo_server.models import SubAgent, SubAgentConfig
# Si DelegationRequest no estuviera, lo asimilamos a kwargs
from tools.gimo_server.services.model_service import ModelService

logger = logging.getLogger("orchestrator.sub_agent_manager")

class SubAgentManager:
    _sub_agents: Dict[str, SubAgent] = {}

    @classmethod
    async def create_sub_agent(cls, parent_id: str, request) -> SubAgent:
        sub_id = str(uuid.uuid4())
        
        # Safe extraction if request is a dict or an object
        model_pref = getattr(request, 'modelPreference', None) or request.get('modelPreference', 'default') if isinstance(request, dict) else 'default'
        constraints = getattr(request, 'constraints', {}) or request.get('constraints', {}) if isinstance(request, dict) else {}

        config = SubAgentConfig(
            model=model_pref, 
            temperature=constraints.get("temperature", 0.7),
            max_tokens=constraints.get("maxTokens", 2048)
        )
        
        agent = SubAgent(
            id=sub_id,
            parentId=parent_id,
            name=f"Sub-Agent {sub_id[:8]}",
            model=model_pref,
            status="starting",
            config=config
        )
        cls._sub_agents[sub_id] = agent
        logger.info(f"Created sub-agent {sub_id} for parent {parent_id}")
        
        return agent

    @classmethod
    def get_sub_agents(cls, parent_id: str = None) -> List[SubAgent]:
        if parent_id:
            return [a for a in cls._sub_agents.values() if a.parentId == parent_id]
        return list(cls._sub_agents.values())

    @classmethod
    def get_sub_agent(cls, sub_id: str) -> Optional[SubAgent]:
        return cls._sub_agents.get(sub_id)

    @classmethod
    async def terminate_sub_agent(cls, sub_id: str):
        if sub_id in cls._sub_agents:
            agent = cls._sub_agents[sub_id]
            agent.status = "terminated"
            logger.info(f"Terminated sub-agent {sub_id}")

    @classmethod
    async def execute_task(cls, sub_id: str, task: str) -> str:
        agent = cls._sub_agents.get(sub_id)
        if not agent:
            raise ValueError(f"SubAgent {sub_id} not found")
        
        if agent.status == "terminated":
             raise ValueError(f"SubAgent {sub_id} is terminated")

        agent.status = "working"
        agent.currentTask = task
        
        try:
            logger.info(f"Sub-agent {sub_id} executing task: {task[:50]}...")
            if not await ModelService.is_backend_ready():
                 ModelService.initialize()

            response = await ModelService.generate(task, agent.model, temperature=agent.config.temperature)
            
            agent.status = "idle"
            agent.currentTask = None
            agent.result = response
            
            return response
        except Exception as e:
            agent.status = "failed"
            agent.currentTask = None
            logger.error(f"Sub-agent {sub_id} failed: {e}")
            raise e
