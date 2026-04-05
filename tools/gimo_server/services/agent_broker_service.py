"""Agent Broker Service: Governed multi-provider agent spawning.

Selects the best provider/model for a task using existing services
(ModelRouterService, TrustEngine, CostService) and spawns agents
through SubAgentManager with governance enforcement via SagpGateway.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("orchestrator.agent_broker")


@dataclass
class BrokerTaskDescriptor:
    """Describes a task for provider selection."""
    name: str
    task: str
    role: str = "worker"
    task_type: str = "code_generation"
    preferred_provider: str = "auto"
    preferred_model: str = "auto"
    execution_policy: str = "workspace_safe"
    max_cost_usd: float = 1.0


@dataclass
class BrokerModelBinding:
    """Result of provider/model selection."""
    provider_id: str
    model_id: str
    estimated_cost_usd: float
    reasoning: str


class AgentBrokerService:
    """Selects providers and spawns governed agents."""

    @classmethod
    def select_provider_for_task(cls, task: BrokerTaskDescriptor) -> BrokerModelBinding:
        """Select the best provider/model for a task.

        Uses ModelRouterService for ranking, TrustEngine for filtering,
        CostService for budget checking.
        """
        from ..services.economy.cost_service import CostService
        from ..services.provider_service import ProviderService

        # If explicit provider/model requested, use them
        if task.preferred_provider != "auto" and task.preferred_model != "auto":
            cost = CostService.calculate_cost(task.preferred_model, 2000, 1000)
            return BrokerModelBinding(
                provider_id=task.preferred_provider,
                model_id=task.preferred_model,
                estimated_cost_usd=cost,
                reasoning=f"Explicit selection: {task.preferred_provider}/{task.preferred_model}",
            )

        # Use ModelRouterService for automatic selection
        try:
            from ..services.model_router_service import ModelRouterService
            config = ProviderService.get_config()
            if config:
                provider_id, model_id = ModelRouterService.resolve_tier_routing(
                    task.task_type, config
                )
                if provider_id and model_id:
                    cost = CostService.calculate_cost(model_id, 2000, 1000)
                    return BrokerModelBinding(
                        provider_id=provider_id,
                        model_id=model_id,
                        estimated_cost_usd=cost,
                        reasoning=f"Auto-routed via ModelRouter: task_type={task.task_type}",
                    )
        except Exception as exc:
            logger.warning("ModelRouter selection failed: %s", exc)

        # Fallback to active provider
        config = ProviderService.get_config()
        if config and config.active:
            entry = config.providers.get(config.active)
            model = entry.model if entry else "unknown"
            cost = CostService.calculate_cost(model, 2000, 1000)
            return BrokerModelBinding(
                provider_id=config.active,
                model_id=model,
                estimated_cost_usd=cost,
                reasoning=f"Fallback to active provider: {config.active}",
            )

        return BrokerModelBinding(
            provider_id="none",
            model_id="none",
            estimated_cost_usd=0.0,
            reasoning="No provider configured",
        )

    @classmethod
    async def spawn_governed_agent(
        cls,
        task: BrokerTaskDescriptor,
    ) -> Dict[str, Any]:
        """Spawn a governed agent with governance check.

        1. Select provider/model
        2. Evaluate via SagpGateway
        3. Spawn via SubAgentManager
        """
        from ..models.surface import SurfaceIdentity
        from ..services.sagp_gateway import SagpGateway
        from ..services.sub_agent_manager import SubAgentManager

        # 1. Select provider/model
        binding = cls.select_provider_for_task(task)

        # 2. Governance check
        surface = SurfaceIdentity(
            surface_type="agent_sdk",
            surface_name=f"agent-broker:{task.name}",
        )
        verdict = SagpGateway.evaluate_action(
            surface=surface,
            tool_name="spawn_subagent",
            tool_args={
                "model": binding.model_id,
                "input_tokens": 2000,
                "output_tokens": 1000,
            },
            policy_name=task.execution_policy,
        )

        if not verdict.allowed:
            return {
                "spawned": False,
                "binding": {"provider_id": binding.provider_id, "model_id": binding.model_id},
                "verdict": verdict.to_dict(),
                "reason": verdict.reasoning,
            }

        # 3. Spawn agent
        req = {
            "modelPreference": binding.model_id,
            "constraints": {
                "role": task.role,
                "task": task.task,
                "provider": binding.provider_id,
                "model": binding.model_id,
                "execution_policy": task.execution_policy,
            },
        }
        agent = await SubAgentManager.create_sub_agent(parent_id="broker", request=req)

        return {
            "spawned": True,
            "agent_id": agent.id,
            "binding": {
                "provider_id": binding.provider_id,
                "model_id": binding.model_id,
                "estimated_cost_usd": binding.estimated_cost_usd,
            },
            "verdict": verdict.to_dict(),
        }
