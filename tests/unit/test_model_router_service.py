import pytest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from tools.gimo_server.services.model_router_service import ModelRouterService
from tools.gimo_server.ops_models import WorkflowNode
from tools.gimo_server.services.recommendation_service import RecommendationService

# ── Model Router & Budget ─────────────────────────────────


@pytest.mark.asyncio
class TestModelRouter:
    async def test_policy_routing(self):
        router = ModelRouterService()
        node = WorkflowNode(id="n", type="llm_call", config={"task_type": "security_review"})
        decision = await router.choose_model(node, _state={})
        assert decision.model != "unknown"
        assert decision.tier >= 1

    async def test_budget_degradation(self):
        router = ModelRouterService()
        node = WorkflowNode(id="n", type="llm_call", config={"task_type": "code_generation"})
        state = {"budget": {"max_cost_usd": 10.0}, "budget_counters": {"cost_usd": 9.5}}
        decision = await router.choose_model(node, _state=state)
        assert decision.model != "unknown"

    async def test_phase6_forced_local_for_security_change(self):
        await asyncio.sleep(0)
        PRIMARY = "test-cloud-model"
        FALLBACK = "test-local-model"
        FORCED = ["SECURITY_CHANGE", "CORE_RUNTIME_CHANGE"]
        decision = ModelRouterService.resolve_phase6_strategy(
            primary_model=PRIMARY,
            fallback_model=FALLBACK,
            forced_local_intents=FORCED,
            intent_effective="SECURITY_CHANGE",
            path_scope=["tools/gimo_server/security/auth.py"],
            primary_failure_reason="",
        )
        assert decision.final_model_used == FALLBACK
        assert decision.fallback_used is False
        assert decision.strategy_reason == "forced_local_only"

    async def test_phase6_400_never_fallback(self):
        await asyncio.sleep(0)
        PRIMARY = "test-cloud-model"
        FALLBACK = "test-local-model"
        FORCED = ["SECURITY_CHANGE", "CORE_RUNTIME_CHANGE"]
        decision = ModelRouterService.resolve_phase6_strategy(
            primary_model=PRIMARY,
            fallback_model=FALLBACK,
            forced_local_intents=FORCED,
            intent_effective="SAFE_REFACTOR",
            path_scope=["tools/gimo_server/services/ops_service.py"],
            primary_failure_reason="400",
        )
        assert decision.fallback_used is False
        assert decision.final_model_used == PRIMARY

    async def test_phase6_429_uses_fallback(self):
        await asyncio.sleep(0)
        PRIMARY = "test-cloud-model"
        FALLBACK = "test-local-model"
        FORCED = ["SECURITY_CHANGE", "CORE_RUNTIME_CHANGE"]
        decision = ModelRouterService.resolve_phase6_strategy(
            primary_model=PRIMARY,
            fallback_model=FALLBACK,
            forced_local_intents=FORCED,
            intent_effective="SAFE_REFACTOR",
            path_scope=["tools/gimo_server/services/ops_service.py"],
            primary_failure_reason="429",
        )
        assert decision.fallback_used is True
        assert decision.final_model_used == FALLBACK
        assert decision.final_status == "FALLBACK_MODEL_USED"

    async def test_phase6_deterministic_decision(self):
        await asyncio.sleep(0)
        kwargs = {
            "primary_model": "test-cloud-model",
            "fallback_model": "test-local-model",
            "forced_local_intents": ["SECURITY_CHANGE", "CORE_RUNTIME_CHANGE"],
            "intent_effective": "SAFE_REFACTOR",
            "path_scope": ["tools/gimo_server/services/provider_service.py"],
            "primary_failure_reason": "timeout",
        }
        a = ModelRouterService.resolve_phase6_strategy(**kwargs)
        b = ModelRouterService.resolve_phase6_strategy(**kwargs)
        assert a.strategy_decision_id == b.strategy_decision_id
        assert a.final_model_used == b.final_model_used


def test_resolve_tier_routing_uses_roles_schema_first():
    cfg = SimpleNamespace(
        providers={
            "orch-main": {"model": "gpt-4o"},
            "wk-1": {"model": "qwen2.5-coder:7b"},
        },
        roles=SimpleNamespace(
            orchestrator=SimpleNamespace(provider_id="orch-main", model="gpt-4o"),
            workers=[SimpleNamespace(provider_id="wk-1", model="qwen2.5-coder:7b")],
        ),
        orchestrator_provider="legacy-orch",
        orchestrator_model="legacy-model",
        worker_provider="legacy-worker",
        worker_model="legacy-worker-model",
    )

    orch_provider, orch_model = ModelRouterService.resolve_tier_routing("analysis", cfg)
    worker_provider, worker_model = ModelRouterService.resolve_tier_routing("code_generation", cfg)

    assert orch_provider == "orch-main"
    assert orch_model == "gpt-4o"
    assert worker_provider == "wk-1"
    assert worker_model == "qwen2.5-coder:7b"


@pytest.mark.asyncio
async def test_recommendation_service_returns_structured_topology():
    class _FakeMonitor:
        @staticmethod
        def get_current_state():
            return {
                "gpu_vendor": "none",
                "gpu_vram_gb": 0.0,
                "gpu_vram_free_gb": 0.0,
                "total_ram_gb": 16.0,
                "wsl2_available": False,
            }

    with patch("tools.gimo_server.services.recommendation_service.HardwareMonitorService.get_instance", return_value=_FakeMonitor()):
        result = await RecommendationService.get_recommendation()

    assert "orchestrator" in result
    assert "worker_pool" in result
    assert result["orchestrator"]["provider"] == result["provider"]
    assert isinstance(result["worker_pool"], list)
    assert result["worker_pool"][0]["count_hint"] == result["workers"]


@pytest.mark.asyncio
async def test_recommendation_service_separates_orchestrator_and_workers_with_reliability():
    class _FakeMonitor:
        @staticmethod
        def get_current_state():
            return {
                "gpu_vendor": "nvidia",
                "gpu_vram_gb": 40.0,
                "gpu_vram_free_gb": 18.0,
                "total_ram_gb": 64.0,
                "wsl2_available": False,
            }

    catalog_models = [
        SimpleNamespace(id="qwen-reasoner-coder:32b", size="32b", capabilities=["code", "reasoning"]),
        SimpleNamespace(id="qwen-coder:7b", size="7b", capabilities=["code"]),
        SimpleNamespace(id="llama-coder:13b", size="13b", capabilities=["code"]),
    ]

    def _fake_reliability(*, provider_type: str, model_id: str):
        if model_id == "qwen-coder:7b":
            return {"score": 0.95, "anomaly": False}
        if model_id == "qwen-reasoner-coder:32b":
            return {"score": 0.90, "anomaly": False}
        if model_id == "llama-coder:13b":
            return {"score": 0.70, "anomaly": False}
        return {"score": 0.50, "anomaly": False}

    with patch("tools.gimo_server.services.recommendation_service.HardwareMonitorService.get_instance", return_value=_FakeMonitor()):
        with patch("tools.gimo_server.services.recommendation_service.ProviderCatalogService.list_available_models", new=AsyncMock(return_value=(catalog_models, []))):
            with patch("tools.gimo_server.services.recommendation_service.OpsService.get_model_reliability", side_effect=_fake_reliability):
                result = await RecommendationService.get_recommendation()

    assert result["orchestrator"]["provider"] == "ollama"
    assert result["orchestrator"]["model"] == "qwen-reasoner-coder:32b"
    assert result["worker_pool"][0]["model"] == "qwen-coder:7b"
    assert result["worker_pool"][0]["count_hint"] >= 1
