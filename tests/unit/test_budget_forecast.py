"""Unit tests for BudgetForecastService — budget forecasts and alert levels."""

from unittest.mock import MagicMock

import pytest

from tools.gimo_server.services.budget_forecast_service import BudgetForecastService
from tools.gimo_server.models.economy import (
    BudgetForecast,
    UserEconomyConfig,
    ProviderBudget,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_storage(total_spend: float = 0.0, provider_spend: float = 0.0, spend_rate: float = 0.0):
    """Create a mock StorageService with controllable cost sub-storage."""
    storage = MagicMock()
    storage.cost.get_total_spend.return_value = total_spend
    storage.cost.get_provider_spend.return_value = provider_spend
    storage.cost.get_spend_rate.return_value = spend_rate
    return storage


def _make_config(
    global_budget: float | None = None,
    thresholds: list[int] | None = None,
    provider_budgets: list[ProviderBudget] | None = None,
) -> UserEconomyConfig:
    return UserEconomyConfig(
        global_budget_usd=global_budget,
        alert_thresholds=thresholds or [50, 25, 10],
        provider_budgets=provider_budgets or [],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGlobalBudgetForecast:
    def test_basic_forecast_remaining_and_hours(self):
        """spend=50, budget=100, burn_rate=1/hr => remaining=50, ~50h to exhaustion."""
        storage = _make_storage(total_spend=50.0, spend_rate=1.0)
        svc = BudgetForecastService(storage)
        config = _make_config(global_budget=100.0)

        forecasts = svc.forecast(config)

        assert len(forecasts) == 1
        f = forecasts[0]
        assert f.scope == "global"
        assert f.current_spend == 50.0
        assert f.remaining == 50.0
        assert f.hours_to_exhaustion == pytest.approx(50.0, abs=0.2)
        assert f.burn_rate_hourly == 1.0

    def test_no_global_budget_produces_no_forecast(self):
        """When global_budget_usd is None, no global forecast is generated."""
        storage = _make_storage(total_spend=10.0)
        svc = BudgetForecastService(storage)
        config = _make_config(global_budget=None)

        forecasts = svc.forecast(config)
        assert len(forecasts) == 0


class TestAlertLevels:
    def test_critical_when_remaining_below_lowest_threshold(self):
        """spend=95, budget=100 => 5% remaining, thresholds [50,25,10] => critical."""
        storage = _make_storage(total_spend=95.0, spend_rate=0.5)
        svc = BudgetForecastService(storage)
        config = _make_config(global_budget=100.0, thresholds=[50, 25, 10])

        forecasts = svc.forecast(config)
        assert len(forecasts) == 1
        assert forecasts[0].alert_level == "critical"

    def test_warning_when_remaining_between_thresholds(self):
        """spend=80, budget=100 => 20% remaining, thresholds [50,25,10] => warning (<=25)."""
        storage = _make_storage(total_spend=80.0, spend_rate=0.5)
        svc = BudgetForecastService(storage)
        config = _make_config(global_budget=100.0, thresholds=[50, 25, 10])

        forecasts = svc.forecast(config)
        assert len(forecasts) == 1
        assert forecasts[0].alert_level == "warning"

    def test_none_when_plenty_remaining(self):
        """spend=30, budget=100 => 70% remaining => 'none'."""
        storage = _make_storage(total_spend=30.0, spend_rate=0.5)
        svc = BudgetForecastService(storage)
        config = _make_config(global_budget=100.0, thresholds=[50, 25, 10])

        forecasts = svc.forecast(config)
        assert len(forecasts) == 1
        assert forecasts[0].alert_level == "none"


class TestProviderBudgetForecast:
    def test_per_provider_forecast(self):
        """Provider budget should use get_provider_spend and include forecast."""
        storage = _make_storage(provider_spend=20.0, spend_rate=0.5)
        svc = BudgetForecastService(storage)
        config = _make_config(
            provider_budgets=[ProviderBudget(provider="openai", max_cost_usd=50.0, period="monthly")],
        )

        forecasts = svc.forecast(config)
        assert len(forecasts) == 1
        f = forecasts[0]
        assert f.scope == "openai"
        assert f.remaining == 30.0
        storage.cost.get_provider_spend.assert_called_once_with("openai", days=30)


class TestZeroBurnRate:
    def test_zero_burn_rate_exhausted_budget(self):
        """When burn_rate=0 and budget is exceeded, hours_to_exhaustion=0."""
        storage = _make_storage(total_spend=110.0, spend_rate=0.0)
        svc = BudgetForecastService(storage)
        config = _make_config(global_budget=100.0)

        forecasts = svc.forecast(config)
        assert len(forecasts) == 1
        f = forecasts[0]
        assert f.remaining == 0.0
        assert f.hours_to_exhaustion == 0.0

    def test_zero_burn_rate_budget_not_exceeded(self):
        """When burn_rate=0 and budget still has remaining, hours_to_exhaustion=None."""
        storage = _make_storage(total_spend=20.0, spend_rate=0.0)
        svc = BudgetForecastService(storage)
        config = _make_config(global_budget=100.0)

        forecasts = svc.forecast(config)
        assert len(forecasts) == 1
        f = forecasts[0]
        assert f.remaining == 80.0
        assert f.hours_to_exhaustion is None
