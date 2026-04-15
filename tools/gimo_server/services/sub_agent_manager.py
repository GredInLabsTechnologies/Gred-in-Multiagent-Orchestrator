import json
import uuid
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path
from tools.gimo_server.models import SubAgent, SubAgentConfig
from tools.gimo_server.services.providers.service import ProviderService
from tools.gimo_server.config import get_settings
from tools.gimo_server.services.providers.catalog_service import ProviderCatalogService
from tools.gimo_server.security.safe_log import sanitize_for_log

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

    @staticmethod
    def _request_value(request: Any, key: str, default: Any = None) -> Any:
        if isinstance(request, dict):
            return request.get(key, default)
        return getattr(request, key, default)

    @classmethod
    def _build_projection(
        cls,
        *,
        parent_id: str,
        workspace_path: Path,
        model_id: str,
        provider_id: str,
        execution_policy: str,
        task: str,
        role: str,
        draft_id: str,
        run_id: str,
        routing: Dict[str, Any],
        name: str | None = None,
    ) -> SubAgent:
        projection_id = run_id or str(uuid.uuid4())
        return SubAgent(
            id=projection_id,
            parentId=parent_id,
            name=name or f"Sub-Agent {projection_id[:8]}",
            model=model_id,
            provider=provider_id,
            status="queued",
            config=SubAgentConfig(model=model_id),
            worktreePath=str(workspace_path),
            description=f"Projection for governed execution {run_id}",
            currentTask=task,
            executionPolicy=execution_policy,
            draftId=draft_id,
            runId=run_id,
            routing=routing,
            delegation={
                "role": role,
                "task": task,
                "summary": str(task or "")[:160],
            },
            authority="ops_run",
            source="spawn",  # R20-007: schema discriminator
        )

    # R20-003: providers that canonically require authentication. For these
    # we refuse to spawn unless diagnostics report both reachable AND
    # auth_status == "ok", regardless of how the provider entry declares
    # its auth_mode (which may be missing or mis-tagged).
    _AUTH_REQUIRED_PROVIDERS = {"openai", "anthropic", "claude", "gemini", "google"}

    @classmethod
    async def _require_provider_readiness(cls, provider_id: str) -> Dict[str, Any]:
        from tools.gimo_server.services.providers.provider_diagnostics_service import ProviderDiagnosticsService

        cfg = ProviderService.get_config()
        entry = (cfg.providers.get(provider_id) if cfg else None)
        auth_mode = str(getattr(entry, "auth_mode", "") or "").strip().lower()
        diag = await ProviderDiagnosticsService._probe_one(provider_id)
        if not diag.reachable:
            raise RuntimeError(f"PROVIDER_NOT_READY:{provider_id}:unreachable")
        pid_norm = str(provider_id or "").strip().lower()
        auth_required = (
            auth_mode not in {"", "none", "api_key_optional"}
            or pid_norm in cls._AUTH_REQUIRED_PROVIDERS
        )
        # R20-003: auth_status "ok" is the only acceptable value when auth is
        # required. Previously "missing" could slip through when auth_mode
        # was mis-declared as empty/api_key_optional, producing ghost spawns.
        if auth_required and str(diag.auth_status or "").strip().lower() != "ok":
            raise RuntimeError(
                f"PROVIDER_NOT_READY:{provider_id}:auth_{diag.auth_status or 'missing'}"
            )
        return {
            "provider_id": diag.provider_id,
            "reachable": bool(diag.reachable),
            "auth_status": diag.auth_status,
            "latency_ms": diag.latency_ms,
            "details": dict(diag.details or {}),
        }

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
        """Create a governed execution record and keep SubAgent as a read projection."""
        from tools.gimo_server.services.agent_broker_service import AgentBrokerService, BrokerTaskDescriptor
        from tools.gimo_server.services.ops.ops_service import OpsService

        workspace_path_str = str(cls._request_value(request, "workspace_path", "") or "").strip()
        if not workspace_path_str:
            raise ValueError("workspace_path is required to spawn a sub-agent. Direct source-repo worktree creation is no longer supported.")

        constraints = dict(cls._request_value(request, "constraints", {}) or {})
        task = str(constraints.get("task") or "").strip()
        role = str(constraints.get("role") or "worker").strip() or "worker"
        provider = str(constraints.get("provider") or "auto").strip() or "auto"
        model = str(constraints.get("model") or cls._request_value(request, "modelPreference", "auto") or "auto").strip() or "auto"
        execution_policy = str(constraints.get("execution_policy") or "workspace_safe").strip() or "workspace_safe"

        if not task:
            raise ValueError("task is required to spawn a governed sub-agent execution")

        resolved_binding = dict(cls._request_value(request, "resolved_binding", {}) or {})
        if not resolved_binding:
            binding = AgentBrokerService.select_provider_for_task(
                BrokerTaskDescriptor(
                    name=str(constraints.get("name") or "sub-agent").strip() or "sub-agent",
                    task=task,
                    role=role,
                    preferred_provider=provider,
                    preferred_model=model,
                    execution_policy=execution_policy,
                    workspace_path=workspace_path_str,
                    parent_id=parent_id,
                )
            )
            resolved_binding = {
                "provider_id": binding.provider_id,
                "model_id": binding.model_id,
                "estimated_cost_usd": binding.estimated_cost_usd,
                "reasoning": binding.reasoning,
            }

        provider_id = str(resolved_binding.get("provider_id") or "").strip()
        model_id = str(resolved_binding.get("model_id") or "").strip()
        if not provider_id or provider_id in {"auto", "none"} or not model_id or model_id in {"auto", "none", "unknown"}:
            raise RuntimeError(f"SPAWN_RESOLUTION_FAILED:{provider}:{model}")

        readiness = await cls._require_provider_readiness(provider_id)
        workspace_path = Path(workspace_path_str)
        provider_cfg = ProviderService.get_config()
        provider_entry = provider_cfg.providers.get(provider_id) if provider_cfg else None
        provider_type = ProviderService.normalize_provider_type(
            getattr(provider_entry, "provider_type", None) or getattr(provider_entry, "type", None) or provider_id
        )
        routing = {
            "provider_id": provider_id,
            "provider_type": provider_type,
            "model_id": model_id,
            "execution_policy": execution_policy,
            "reasoning": str(resolved_binding.get("reasoning") or ""),
            "estimated_cost_usd": float(resolved_binding.get("estimated_cost_usd") or 0.0),
            "delegation": {
                "role": role,
                "task": task,
                "summary": str(task)[:160],
                "parent_id": parent_id,
            },
            "readiness": readiness,
        }

        # R20-001: sub-agent spawns are ALWAYS cognitive_agent operators
        # (no human UI). Propagate an explicit operator_class so the policy
        # gate whitelists the resulting draft.
        operator_class_value = str(
            constraints.get("operator_class") or "cognitive_agent"
        )
        surface_type_value = str(constraints.get("surface_type") or "agent_sdk")

        draft = OpsService.create_draft(
            prompt=task,
            context={
                "kind": "sub_agent_spawn",
                "parent_id": parent_id,
                "workspace_root": str(workspace_path),
                "requested_provider": provider,
                "requested_model": model,
                "provider_id": provider_id,
                "provider_type": provider_type,
                "model": model_id,
                "execution_policy_name": execution_policy,
                "operator_class": operator_class_value,
                "surface_type": surface_type_value,
                "routing_decision": {
                    "provider": provider_id,
                    "model": model_id,
                    "profile": {"execution_policy": execution_policy},
                    "delegation": routing["delegation"],
                    "reasoning": routing["reasoning"],
                    "readiness": readiness,
                },
            },
            provider=provider_id,
            status="draft",
            operator_class=operator_class_value,
        )
        approved = OpsService.approve_draft(draft.id, approved_by=f"sub_agent:{parent_id}")
        run = OpsService.create_run(approved.id)
        projection = cls._build_projection(
            parent_id=parent_id,
            workspace_path=workspace_path,
            model_id=model_id,
            provider_id=provider_id,
            execution_policy=execution_policy,
            task=task,
            role=role,
            draft_id=draft.id,
            run_id=run.id,
            routing=routing,
            name=str(constraints.get("name") or "").strip() or None,
        )
        cls._sub_agents[projection.id] = projection
        cls._persist()
        logger.info("Spawned governed execution %s for parent %s via %s/%s", run.id, parent_id, provider_id, model_id)
        return projection

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
        logger.info("Using provisioned workspace for sub-agent %s at %s", sub_id, worktree_path)

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
        logger.info("Created sub-agent %s for parent %s", sub_id, parent_id)
        
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
                        description=f"Auto-discovered agent powered by Ollama model {m_id}",
                        source="auto_discovery",  # R20-007: schema discriminator
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
            logger.error("Failed to sync with Ollama: %s", e)

    @classmethod
    def get_sub_agents(
        cls,
        parent_id: str = None,
        *,
        source: Optional[str] = None,
        exclude_orphans: bool = False,
    ) -> List[SubAgent]:
        """List sub-agents.

        R20-007: accepts ``source`` ("auto_discovery"|"spawn") to disambiguate
        the auto-discovered inventory from governed spawn projections, and
        ``exclude_orphans`` to drop spawn projections whose runId is missing
        — these accumulate when a spawn fails readiness gates and no run is
        created.
        """
        agents = list(cls._sub_agents.values())
        if parent_id:
            agents = [a for a in agents if a.parentId == parent_id]
        if source:
            agents = [a for a in agents if str(getattr(a, "source", "spawn")) == source]
        if exclude_orphans:
            agents = [
                a
                for a in agents
                if str(getattr(a, "source", "spawn")) != "spawn"
                or bool(getattr(a, "runId", None))
            ]
        return agents

    @classmethod
    def gc_orphan_spawns(cls) -> int:
        """R20-007: drop spawn projections whose runId is None/empty.

        Returns the number of entries removed. Callers decide when to run
        this (startup reconcile, manual ops command, etc.).
        """
        removed = 0
        for agent_id in list(cls._sub_agents.keys()):
            agent = cls._sub_agents[agent_id]
            if str(getattr(agent, "source", "spawn")) != "spawn":
                continue
            if not getattr(agent, "runId", None):
                del cls._sub_agents[agent_id]
                removed += 1
        if removed:
            cls._persist()
            logger.info("gc_orphan_spawns: removed %d orphan spawn projection(s)", removed)
        return removed

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
            
            logger.info("Terminated sub-agent %s", sub_id)
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
            logger.info("Sub-agent %s executing task: %s...", sub_id, task[:50])
            
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
            logger.error(
                "Sub-agent %s failed: %s",
                sanitize_for_log(sub_id),
                sanitize_for_log(e),
            )
            raise e
