import json
import uuid
import logging
from typing import Dict, List, Optional
from pathlib import Path
from tools.gimo_server.models import SubAgent, SubAgentConfig
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.config import get_settings
from tools.gimo_server.services.provider_catalog_service import ProviderCatalogService

logger = logging.getLogger("orchestrator.sub_agent_manager")

INVENTORY_FILE = get_settings().ops_data_dir.parent / "runtime" / "sub_agents.json"

class SubAgentManager:
    """Gestiona el ciclo de vida, spawn y estado de agentes secundarios.
    
    **Model discovery authority only. Provisioned workspace lifecycle stays external.**
    """
    _sub_agents: Dict[str, SubAgent] = {}
    _synced_models: set[str] = set()

    @classmethod
    def _workspace_exists(cls, workspace_path: str | None) -> bool:
        if not workspace_path:
            return True
        return Path(workspace_path).exists()

    @classmethod
    def _load_inventory(cls) -> Dict[str, SubAgent]:
        """Load persisted sub-agent inventory from disk."""
        if not INVENTORY_FILE.exists():
            return {}
        try:
            data = json.loads(INVENTORY_FILE.read_text(encoding="utf-8"))
            result = {}
            for agent_id, agent_data in data.items():
                result[agent_id] = SubAgent(**agent_data)
            return result
        except Exception as e:
            logger.warning("Failed to load sub-agent inventory: %s", e)
            return {}

    @classmethod
    def _persist(cls):
        """Atomically persist sub-agent inventory to disk."""
        INVENTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = INVENTORY_FILE.with_suffix(".tmp")
        try:
            data = {}
            for agent_id, agent in cls._sub_agents.items():
                data[agent_id] = agent.model_dump() if hasattr(agent, 'model_dump') else agent.__dict__
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            tmp.rename(INVENTORY_FILE)
        except Exception as e:
            logger.error("Failed to persist sub-agent inventory: %s", e)
            tmp.unlink(missing_ok=True)

    @classmethod
    async def startup_reconcile(cls):
        """Reconcile persisted inventory with provisioned workspace state on startup."""
        stored = cls._load_inventory()
        reconciled = {}
        removed_missing_workspaces = 0

        for agent_id, agent in stored.items():
            if not cls._workspace_exists(getattr(agent, "worktreePath", None)):
                removed_missing_workspaces += 1
                logger.info("Removed sub-agent with missing provisioned workspace: %s", agent_id)
                continue
            reconciled[agent_id] = agent

        cls._sub_agents = reconciled
        cls._persist()
        await cls.sync_with_ollama()
        tracked_workspaces = sum(1 for agent in cls._sub_agents.values() if getattr(agent, "worktreePath", None))
        logger.info(
            "SubAgent reconcile complete: %d agents, %d provisioned workspaces, %d removed missing workspaces",
            len(cls._sub_agents),
            tracked_workspaces,
            removed_missing_workspaces,
        )

    @classmethod
    async def spawn_via_draft(cls, parent_id: str, request) -> SubAgent:
        """R18 Change 3 — governance-unified spawn path.

        Records an OpsService draft entry before creating the sub-agent so
        every spawn traverses the same governance spine as /ops/drafts
        (policy gate, trust, cost, proof chain). Existing callers of
        ``create_sub_agent`` continue to work; new call sites should use
        this method. Full migration is tracked in the R18 report.
        """
        try:
            from tools.gimo_server.services.ops.ops_service import OpsService
            model_pref = (
                getattr(request, "modelPreference", None)
                or (request.get("modelPreference") if isinstance(request, dict) else None)
                or "default"
            )
            OpsService.create_draft(
                prompt=f"spawn_sub_agent(parent={parent_id}, model={model_pref})",
                context={
                    "kind": "sub_agent_spawn",
                    "parent_id": parent_id,
                    "model": model_pref,
                },
                provider="sub_agent_manager",
                status="draft",
            )
        except Exception as e:
            logger.warning("spawn_via_draft: draft recording failed (non-fatal): %s", e)
        return await cls.create_sub_agent(parent_id, request)

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
        
        workspace_path_str = getattr(request, 'workspace_path', None) or (request.get('workspace_path') if isinstance(request, dict) else None)
        
        if not workspace_path_str:
            raise ValueError("workspace_path is required to spawn a sub-agent. Direct source-repo worktree creation is no longer supported.")

        worktree_path = Path(workspace_path_str)
        logger.info(f"Using provisioned workspace for sub-agent {sub_id} at {worktree_path}")

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
        cls._persist()
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
                logger.info(
                    "Sub-agent %s terminated; provisioned workspace lifecycle remains external: %s",
                    sub_id,
                    agent.worktreePath,
                )
            
            logger.info(f"Terminated sub-agent {sub_id}")
            cls._persist()

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

            # Smart Wake already ensures Ollama is ready if needed
            result = await ProviderService.static_generate(
                prompt=task, 
                context={"model": agent.model, "temperature": agent.config.temperature}
            )
            response = result.get("content", "")
            
            agent.status = "idle"
            agent.currentTask = None
            agent.result = response
            
            return response
        except Exception as e:
            agent.status = "failed"
            agent.currentTask = None
            logger.error(f"Sub-agent {sub_id} failed: {e}")
            raise e
