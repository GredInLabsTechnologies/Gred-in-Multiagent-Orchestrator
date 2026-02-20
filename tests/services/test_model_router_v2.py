import pytest
from unittest.mock import patch, MagicMock
from tools.gimo_server.services.model_router_service import ModelRouterService
from tools.gimo_server.ops_models import WorkflowNode, OpsConfig, UserEconomyConfig, EcoModeConfig

def test_model_router_degrade_logic():
    service = ModelRouterService()
    # Opus -> Sonnet -> Haiku -> Local
    assert service._degrade("opus") == "sonnet"
    assert service._degrade("sonnet") == "haiku"
    assert service._degrade("haiku") == "local"
    assert service._degrade("unknown") == "unknown"

@pytest.mark.asyncio
async def test_model_router_low_budget_degradation():
    service = ModelRouterService()
    node = WorkflowNode(id="test", type="llm_call", config={"task_type": "code_generation"})

    # Normal budget
    state_normal = {"budget": {"max_cost_usd": 10.0}, "budget_counters": {"cost_usd": 1.0}}
    decision_normal = await service.choose_model(node, state_normal)
    assert decision_normal.model == "sonnet" # Default for code_gen

    # Low budget (spent 9/10 = 90%)
    state_low = {"budget": {"max_cost_usd": 10.0}, "budget_counters": {"cost_usd": 9.0}}
    decision_low = await service.choose_model(node, state_low)
    assert decision_low.model == "haiku" # Degraded from sonnet
    assert "low_budget" in decision_low.reason

def test_promote_eco_mode_recommendation():
    service = ModelRouterService()
    node = WorkflowNode(id="test", type="llm_call", config={"task_type": "security_review"})
    state = {}

    # Mock OpsService.get_config to return config with eco_mode enabled (binary mode)
    mock_config = OpsConfig(
        economy=UserEconomyConfig(
            eco_mode=EcoModeConfig(mode="binary", floor_tier="local")
        )
    )
    with patch("tools.gimo_server.services.ops_service.OpsService") as MockOps:
        MockOps.get_config.return_value = mock_config
        rec = service.promote_eco_mode(node, state)

    assert rec["recommendations"]["best"]["model"] == "opus"  # High tier for security
    assert rec["recommendations"]["eco"]["model"] == "sonnet"
    assert rec["recommendations"]["eco"]["impact"]["saving_pct"] > 0
    assert rec["saving_prospect"] > 0


@pytest.mark.asyncio
async def test_model_router_resolves_tier_to_provider_model_map():
    service = ModelRouterService()
    node = WorkflowNode(id="test", type="llm_call", config={"task_type": "security_review"})

    mock_config = OpsConfig(
        economy=UserEconomyConfig(
            provider_model_map={
                "openai": {
                    "opus": "gpt-4.1",
                    "sonnet": "gpt-4o",
                    "haiku": "gpt-4o-mini",
                }
            }
        )
    )

    mock_provider_cfg = MagicMock()
    mock_provider_cfg.provider_type = "openai"
    mock_provider_cfg.active = "openai_main"
    mock_provider_cfg.providers = {}

    with patch("tools.gimo_server.services.ops_service.OpsService") as MockOps:
        MockOps.get_config.return_value = mock_config
        with patch("tools.gimo_server.services.provider_service.ProviderService") as MockProvider:
            MockProvider.get_config.return_value = mock_provider_cfg
            decision = await service.choose_model(node, {})

    assert decision.tier == "opus"
    assert decision.model == "gpt-4.1"
    assert "provider_map:openai:opus->gpt-4.1" in decision.reason
