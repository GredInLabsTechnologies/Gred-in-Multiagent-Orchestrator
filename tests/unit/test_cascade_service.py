"""Unit tests for CascadeService — model escalation with quality gates."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.gimo_server.services.economy.cascade_service import CascadeService
from tools.gimo_server.models.economy import CascadeConfig, CascadeResult, QualityRating
from tools.gimo_server.services.model_inventory_service import ModelEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_model_entry(model_id: str, tier: int, cost_in: float = 1.0, cost_out: float = 2.0) -> ModelEntry:
    return ModelEntry(
        model_id=model_id,
        provider_id="test-provider",
        provider_type="openai",
        is_local=False,
        quality_tier=tier,
        capabilities={"chat"},
        cost_input=cost_in,
        cost_output=cost_out,
    )


FAKE_MODELS = [
    _make_model_entry("cheap-model", tier=2, cost_in=0.1, cost_out=0.3),
    _make_model_entry("mid-model", tier=3, cost_in=1.0, cost_out=3.0),
    _make_model_entry("expensive-model", tier=4, cost_in=5.0, cost_out=15.0),
    _make_model_entry("flagship-model", tier=5, cost_in=15.0, cost_out=75.0),
]


def _build_service() -> tuple[CascadeService, AsyncMock]:
    provider_service = MagicMock()
    provider_service.generate = AsyncMock()
    model_router = MagicMock()
    svc = CascadeService(provider_service, model_router)
    return svc, provider_service.generate


def _quality(score: int) -> QualityRating:
    return QualityRating(score=score, alerts=[], heuristics={})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCascadeFirstAttemptSuccess:
    @pytest.mark.asyncio
    async def test_meets_threshold_on_first_attempt(self):
        """When the first model meets the quality threshold, chain has 1 entry."""
        svc, gen_mock = _build_service()
        gen_mock.return_value = {
            "content": "great answer",
            "cost_usd": 0.002,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }

        config = CascadeConfig(enabled=True, quality_threshold=60, max_escalations=2)
        context = {"model": "cheap-model", "task_type": "code"}

        with patch(
            "tools.gimo_server.services.economy.cascade_service.QualityService.analyze_output",
            return_value=_quality(80),
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.ModelInventoryService.get_available_models",
            return_value=FAKE_MODELS,
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.CostService.calculate_cost",
            return_value=0.01,
        ):
            result = await svc.execute_with_cascade("do stuff", context, config)

        assert result.success is True
        assert len(result.cascade_chain) == 1
        assert result.cascade_chain[0]["model"] == "cheap-model"
        assert result.total_cost_usd == pytest.approx(0.002)


class TestCascadeEscalation:
    @pytest.mark.asyncio
    async def test_escalates_to_higher_tier_on_low_quality(self):
        """When first attempt is below threshold, service escalates and chain has 2 entries."""
        svc, gen_mock = _build_service()

        # First attempt: low quality; second attempt: good quality
        gen_mock.side_effect = [
            {"content": "bad", "cost_usd": 0.001, "prompt_tokens": 50, "completion_tokens": 20},
            {"content": "good", "cost_usd": 0.005, "prompt_tokens": 100, "completion_tokens": 60},
        ]

        config = CascadeConfig(enabled=True, quality_threshold=70, max_escalations=2)
        context = {"model": "cheap-model", "task_type": "code"}

        quality_scores = iter([_quality(30), _quality(85)])

        with patch(
            "tools.gimo_server.services.economy.cascade_service.QualityService.analyze_output",
            side_effect=lambda *a, **kw: next(quality_scores),
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.ModelInventoryService.get_available_models",
            return_value=FAKE_MODELS,
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.ModelInventoryService.find_model",
            return_value=_make_model_entry("cheap-model", tier=2),
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.ModelInventoryService.get_models_for_tier",
            return_value=[_make_model_entry("mid-model", tier=3)],
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.CostService.calculate_cost",
            return_value=0.05,
        ):
            result = await svc.execute_with_cascade("do stuff", context, config)

        assert result.success is True
        assert len(result.cascade_chain) == 2
        assert result.cascade_chain[0]["success"] is False
        assert result.cascade_chain[1]["success"] is True


class TestCascadeMaxEscalations:
    @pytest.mark.asyncio
    async def test_stops_at_max_escalations(self):
        """When max_escalations is reached without meeting threshold, success=False."""
        svc, gen_mock = _build_service()

        # All attempts produce low quality
        gen_mock.return_value = {
            "content": "mediocre",
            "cost_usd": 0.001,
            "prompt_tokens": 50,
            "completion_tokens": 20,
        }

        config = CascadeConfig(enabled=True, quality_threshold=90, max_escalations=1)
        context = {"model": "cheap-model", "task_type": "code"}

        tier_entries = {
            3: [_make_model_entry("mid-model", tier=3)],
            4: [_make_model_entry("expensive-model", tier=4)],
            5: [],
        }

        call_count = [0]
        def find_model_side_effect(model_id):
            # Return the entry matching the model being used
            for m in FAKE_MODELS:
                if m.model_id == model_id:
                    return m
            return _make_model_entry(model_id, tier=2)

        def get_tier_side_effect(min_t, max_t=5):
            entries = []
            for t in range(min_t, max_t + 1):
                entries.extend(tier_entries.get(t, []))
            return entries

        with patch(
            "tools.gimo_server.services.economy.cascade_service.QualityService.analyze_output",
            return_value=_quality(40),
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.ModelInventoryService.get_available_models",
            return_value=FAKE_MODELS,
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.ModelInventoryService.find_model",
            side_effect=find_model_side_effect,
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.ModelInventoryService.get_models_for_tier",
            side_effect=get_tier_side_effect,
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.CostService.calculate_cost",
            return_value=0.05,
        ):
            result = await svc.execute_with_cascade("do stuff", context, config)

        assert result.success is False
        # max_escalations=1 means max 2 attempts (1 initial + 1 escalation)
        assert len(result.cascade_chain) == 2


class TestCascadeBudgetLimit:
    @pytest.mark.asyncio
    async def test_budget_stops_cascade_early(self):
        """When node budget is exceeded, cascade stops before max_escalations."""
        svc, gen_mock = _build_service()

        gen_mock.return_value = {
            "content": "ok",
            "cost_usd": 0.50,  # expensive
            "prompt_tokens": 1000,
            "completion_tokens": 500,
        }

        config = CascadeConfig(enabled=True, quality_threshold=90, max_escalations=3)
        context = {"model": "cheap-model", "task_type": "code"}
        node_budget = {"max_cost_usd": 0.60}  # Will exceed after 2nd attempt

        with patch(
            "tools.gimo_server.services.economy.cascade_service.QualityService.analyze_output",
            return_value=_quality(30),
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.ModelInventoryService.get_available_models",
            return_value=FAKE_MODELS,
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.ModelInventoryService.find_model",
            return_value=_make_model_entry("cheap-model", tier=2),
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.ModelInventoryService.get_models_for_tier",
            return_value=[_make_model_entry("mid-model", tier=3)],
        ), patch(
            "tools.gimo_server.services.economy.cascade_service.CostService.calculate_cost",
            return_value=0.05,
        ):
            result = await svc.execute_with_cascade("do stuff", context, config, node_budget=node_budget)

        # Should stop after 1 attempt because total_cost (0.50) < 0.60 but after 2nd it would be 1.0
        # Actually: first attempt costs 0.50, which is < 0.60 so it tries to escalate.
        # After first attempt, total_cost=0.50 < 0.60, so budget check passes, escalates.
        # Second attempt costs another 0.50, total_cost=1.00 >= 0.60, so stops.
        assert result.success is False
        assert len(result.cascade_chain) <= 2
        assert result.total_cost_usd >= 0.50
