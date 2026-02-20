import uuid
import logging
from typing import Dict, List, Optional
from tools.repo_orchestrator.models import SubAgent, SubAgentConfig, DelegationRequest
from tools.repo_orchestrator.services.model_service import ModelService
from tools.repo_orchestrator.services.system_prompt_service import SystemPromptService

logger = logging.getLogger("orchestrator.sub_agent_manager")

class SubAgentManager:
    _sub_agents: Dict[str, SubAgent] = {}
    _system_prompts: Dict[str, str] = {}

    @classmethod
    async def create_sub_agent(cls, parent_id: str, request: DelegationRequest) -> SubAgent:
        sub_id = str(uuid.uuid4())
        # Filter constraints to match SubAgentConfig fields if needed, 
        # but here we pass them as kwargs assuming they match or are extra
        # For now, simplistic config creation
        config = SubAgentConfig(
            model=request.modelPreference, 
            temperature=request.constraints.get("temperature", 0.7),
            max_tokens=request.constraints.get("maxTokens", 2048)
        )
        
        agent = SubAgent(
            id=sub_id,
            parentId=parent_id,
            name=f"Sub-Agent {sub_id[:8]}",
            model=request.modelPreference,
            status="starting",
            config=config
        )
        cls._sub_agents[sub_id] = agent
        cls._system_prompts[sub_id] = SystemPromptService.build_master_prompt(
            parent_id=parent_id,
            sub_task=request.subTaskDescription,
            constraints=request.constraints,
        )
        logger.info(f"Created sub-agent {sub_id} for parent {parent_id}")
        
        from tools.repo_orchestrator.ws.manager import manager
        await manager.broadcast({
            "type": "sub_agent_update",
            "agent_id": sub_id,
            "parent_id": parent_id,
            "payload": agent.model_dump()
        })
        
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
            cls._system_prompts.pop(sub_id, None)
            logger.info(f"Terminated sub-agent {sub_id}")
            
            from tools.repo_orchestrator.ws.manager import manager
            await manager.broadcast({
                "type": "sub_agent_update",
                "agent_id": sub_id,
                "payload": agent.model_dump()
            })

    @classmethod
    async def execute_task(cls, sub_id: str, task: str) -> str:
        agent = cls._sub_agents.get(sub_id)
        if not agent:
            raise ValueError(f"SubAgent {sub_id} not found")
        
        if agent.status == "terminated":
             raise ValueError(f"SubAgent {sub_id} is terminated")

        agent.status = "working"
        agent.currentTask = task
        
        from tools.repo_orchestrator.ws.manager import manager
        await manager.broadcast({
            "type": "sub_agent_update",
            "agent_id": sub_id,
            "payload": agent.model_dump()
        })
        
        try:
            logger.info(f"Sub-agent {sub_id} executing task: {task[:50]}...")
            # We initialize the model service (idempotent usually, or check status)
            if not await ModelService.is_backend_ready():
                # Try to initialize default if not ready
                 ModelService.initialize()

            system_prompt = cls._system_prompts.get(sub_id) or SystemPromptService.build_master_prompt(
                parent_id=agent.parentId,
                sub_task=task,
                constraints={},
            )
            execution_prompt = SystemPromptService.compose_execution_prompt(
                system_prompt=system_prompt,
                task=task,
            )
            response = await ModelService.generate(
                execution_prompt,
                agent.model,
                temperature=agent.config.temperature,
                system_prompt=system_prompt,
            )
            
            agent.status = "idle"
            agent.currentTask = None
            agent.result = response
            
            await manager.broadcast({
                "type": "sub_agent_update",
                "agent_id": sub_id,
                "payload": agent.model_dump()
            })
            
            return response
        except Exception as e:
            agent.status = "failed"
            agent.currentTask = None
            logger.error(f"Sub-agent {sub_id} failed: {e}")
            
            await manager.broadcast({
                "type": "sub_agent_update",
                "agent_id": sub_id,
                "payload": agent.model_dump()
            })
            raise e
