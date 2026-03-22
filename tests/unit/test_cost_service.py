"""Unit tests for CostService — pricing registry, cost calculations, and ROI."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from tools.gimo_server.services.cost_service import CostService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PRICING = {
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "local": {"input": 0.0, "output": 0.0},
}


@pytest.fixture(autouse=True)
def _reset_cost_service():
    """Reset CostService class state before each test."""
    CostService._PRICING_LOADED = False
    CostService.PRICING_REGISTRY = {}
    yield
    CostService._PRICING_LOADED = False
    CostService.PRICING_REGISTRY = {}


@pytest.fixture()
def _load_sample_pricing():
    """Inject sample pricing directly (skip file I/O)."""
    CostService.PRICING_REGISTRY = dict(SAMPLE_PRICING)
    CostService._PRICING_LOADED = True


# ---------------------------------------------------------------------------
# load_pricing
# ---------------------------------------------------------------------------

class TestLoadPricing:
    def test_load_pricing_sets_loaded_flag(self, tmp_path):
        pricing_file = tmp_path / "model_pricing.json"
        pricing_file.write_text(json.dumps(SAMPLE_PRICING))

        with patch("tools.gimo_server.config.DATA_DIR", str(tmp_path)):
            CostService.load_pricing()

        assert CostService._PRICING_LOADED is True
        assert "gpt-4o" in CostService.PRICING_REGISTRY
        assert CostService.PRICING_REGISTRY["gpt-4o"]["input"] == 2.5

    def test_load_pricing_missing_file_falls_back_to_local(self, tmp_path):
        """When the pricing JSON does not exist, registry should contain 'local' only."""
        with patch("tools.gimo_server.config.DATA_DIR", str(tmp_path)):
            CostService.load_pricing()

        assert CostService.PRICING_REGISTRY == {"local": {"input": 0.0, "output": 0.0}}

    def test_load_pricing_skips_if_already_loaded(self):
        CostService._PRICING_LOADED = True
        CostService.PRICING_REGISTRY = {"sentinel": {"input": 1.0, "output": 2.0}}

        CostService.load_pricing()

        # Should not overwrite the registry since already loaded
        assert "sentinel" in CostService.PRICING_REGISTRY


# ---------------------------------------------------------------------------
# get_pricing
# ---------------------------------------------------------------------------

class TestGetPricing:
    def test_known_model_returns_correct_pricing(self, _load_sample_pricing):
        pricing = CostService.get_pricing("gpt-4o")
        assert pricing == {"input": 2.5, "output": 10.0}

    def test_alias_maps_to_canonical(self, _load_sample_pricing):
        """'sonnet' alias should map to claude-3-5-sonnet pricing."""
        pricing = CostService.get_pricing("sonnet")
        assert pricing["input"] == 3.0
        assert pricing["output"] == 15.0

    def test_unknown_model_falls_back_to_local(self, _load_sample_pricing):
        pricing = CostService.get_pricing("totally-unknown-model-xyz")
        assert pricing == {"input": 0.0, "output": 0.0}


# ---------------------------------------------------------------------------
# calculate_cost
# ---------------------------------------------------------------------------

class TestCalculateCost:
    @pytest.mark.parametrize(
        "model, input_tokens, output_tokens, expected_cost",
        [
            # gpt-4o: 2.5/1M in, 10.0/1M out
            ("gpt-4o", 1_000_000, 0, 2.5),
            ("gpt-4o", 0, 1_000_000, 10.0),
            ("gpt-4o", 500_000, 500_000, 1.25 + 5.0),
            # local: free
            ("local", 1_000_000, 1_000_000, 0.0),
            # small usage
            ("gpt-4o", 1000, 500, round((1000 / 1e6) * 2.5 + (500 / 1e6) * 10.0, 6)),
        ],
    )
    def test_calculate_cost_math(self, _load_sample_pricing, model, input_tokens, output_tokens, expected_cost):
        result = CostService.calculate_cost(model, input_tokens, output_tokens)
        assert result == pytest.approx(expected_cost, abs=1e-6)


# ---------------------------------------------------------------------------
# get_provider
# ---------------------------------------------------------------------------

class TestGetProvider:
    @pytest.mark.parametrize(
        "model_name, expected_provider",
        [
            ("claude-3-opus-20240229", "anthropic"),
            ("claude-3-5-sonnet", "anthropic"),
            ("gpt-4o", "openai"),
            ("gpt-4o-mini", "openai"),
            ("gemini-2.0-flash", "google"),
            ("deepseek-chat", "deepseek"),
            ("meta-llama-3-70b", "meta"),
            ("qwen-2.5-72b", "qwen"),
            ("local", "local"),
            ("completely-alien-model", "unknown"),
        ],
    )
    def test_provider_inference(self, model_name, expected_provider):
        assert CostService.get_provider(model_name) == expected_provider


# ---------------------------------------------------------------------------
# get_impact_comparison
# ---------------------------------------------------------------------------

class TestGetImpactComparison:
    def test_cheaper_model_shows_better(self, _load_sample_pricing):
        """Comparing expensive model A to cheaper model B should report 'better' savings."""
        result = CostService.get_impact_comparison("claude-3-opus-20240229", "gpt-4o-mini")
        assert result["status"] == "better"
        assert result["saving_pct"] > 0

    def test_more_expensive_model_shows_worse(self, _load_sample_pricing):
        """Comparing cheap model A to expensive model B should report 'worse'."""
        result = CostService.get_impact_comparison("gpt-4o-mini", "claude-3-opus-20240229")
        assert result["status"] == "worse"
        assert result["saving_pct"] < 0

    def test_same_model_shows_equal(self, _load_sample_pricing):
        result = CostService.get_impact_comparison("gpt-4o", "gpt-4o")
        assert result["status"] == "equal"
        assert result["saving_pct"] == 0

    def test_zero_cost_model_a_returns_neutral(self, _load_sample_pricing):
        """When model_a has zero average pricing, status should be 'neutral'."""
        result = CostService.get_impact_comparison("local", "gpt-4o")
        assert result["status"] == "neutral"
        assert result["saving_pct"] == 0


# ---------------------------------------------------------------------------
# calculate_roi
# ---------------------------------------------------------------------------

class TestCalculateRoi:
    def test_basic_roi_math(self):
        # quality=80, cost=0.01 => 80 / 0.010001 ~ 7999.2
        roi = CostService.calculate_roi(80, 0.01)
        assert roi == pytest.approx(80 / 0.010001, rel=1e-3)

    def test_zero_cost_returns_high_roi(self):
        """Cost=0 should use epsilon to avoid division by zero."""
        roi = CostService.calculate_roi(100, 0.0)
        assert roi > 1_000_000  # Very high ROI when cost is essentially zero

    def test_zero_quality_returns_zero(self):
        roi = CostService.calculate_roi(0, 10.0)
        assert roi == pytest.approx(0.0, abs=1e-6)
