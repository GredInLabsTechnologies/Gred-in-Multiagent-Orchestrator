import uuid
import logging
from typing import Dict, List, Optional
from pathlib import Path
from tools.gimo_server.models import SubAgent, SubAgentConfig
from tools.gimo_server.services.model_service import ModelService
from tools.gimo_server.services.git_service import GitService
from tools.gimo_server.config import WORKTREES_DIR, REPO_ROOT_DIR
from tools.gimo_server.services.provider_catalog_service import ProviderCatalogService

logger = logging.getLogger("orchestrator.sub_agent_manager")

class SubAgentManager:
    _sub_agents: Dict[str, SubAgent] = {}
    _synced_models: set[str] = set()

    @classmethod
    def _ensure_worktrees_dir(cls):
        WORKTREES_DIR.mkdir(parents=True, exist_ok=True)

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
        
        # Create isolated worktree
        cls._ensure_worktrees_dir()
        worktree_path = WORKTREES_DIR / sub_id
        try:
            # We add worktree relative to REPO_ROOT_DIR
            GitService.add_worktree(REPO_ROOT_DIR, worktree_path)
            logger.info(f"Created isolated worktree at {worktree_path}")
        except Exception as e:
            logger.error(f"Failed to create worktree for sub-agent {sub_id}: {e}")
            worktree_path = None

        agent = SubAgent(
            id=sub_id,
            parentId=parent_id,
            name=f"Sub-Agent {sub_id[:8]}",
            model=model_pref,
            status="starting",
            config=config,
            worktreePath=str(worktree_path) if worktree_path else None
        )
        cls._sub_agents[sub_id] = agent
        logger.info(f"Created sub-agent {sub_id} for parent {parent_id}")
        
        return agent

    @classmethod
    async def sync_with_ollama(cls):
        """Fetch installed models from Ollama and register them as agents if missing."""
        try:
            is_alive = await ProviderCatalogService._ollama_health()
            installed_models = await ProviderCatalogService._ollama_list_installed()
            
            for model_info in installed_models:
                m_id = model_info.id
                if m_id not in cls._synced_models:
                    # Register this model as a persistent available agent
                    agent = SubAgent(
                        id=f"ollama_{m_id.replace(':', '_')}",
                        parentId="system_discovery",
                        name=f"Ollama: {m_id}",
                        model=m_id,
                        status="idle" if is_alive else "offline",
                        config=SubAgentConfig(model=m_id),
                        description=f"Auto-discovered agent powered by Ollama model {m_id}"
                    )
                    cls._sub_agents[agent.id] = agent
                    cls._synced_models.add(m_id)
                    logger.info(f"Dynamically registered agent for model: {m_id} (Status: {agent.status})")
                else:
                    # Update status of existing agent if it was offline
                    agent_id = f"ollama_{m_id.replace(':', '_')}"
                    if agent_id in cls._sub_agents:
                        cls._sub_agents[agent_id].status = "idle" if is_alive else "offline"
        except Exception as e:
            logger.error(f"Failed to sync with Ollama: {e}")

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
            
            if agent.worktreePath:
                try:
                    GitService.remove_worktree(REPO_ROOT_DIR, Path(agent.worktreePath))
                    logger.info(f"Removed isolated worktree for sub-agent {sub_id}")
                except Exception as e:
                    logger.error(f"Failed to remove worktree for sub-agent {sub_id}: {e}")
            
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
            
            # Smart Wake: Ensure Ollama is running if using an Ollama model
            if agent.id.startswith("ollama_"):
                logger.info("Ollama agent detected. Ensuring service is ready...")
                if not await ProviderCatalogService.ensure_ollama_ready():
                    logger.error("Failed to wake up Ollama service.")
                    agent.status = "offline"
                    raise RuntimeError("Ollama service is offline and could not be started.")

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
