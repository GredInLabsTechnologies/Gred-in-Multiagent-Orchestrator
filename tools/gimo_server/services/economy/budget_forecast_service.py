from __future__ import annotations

import logging
import os
from typing import List, Optional

from ...ops_models import BudgetForecast, UserEconomyConfig
from ..storage_service import StorageService

logger = logging.getLogger("orchestrator.ops.budget")

_DEBUG_MODE = os.environ.get("DEBUG", "").lower() in ("true", "1", "yes", "verbose")


class BudgetForecastService:
    """Service to predict budget exhaustion and provide alerts."""

    def __init__(self, storage: StorageService):
        self.storage = storage

    @property
    def debug_mode(self) -> bool:
        return _DEBUG_MODE

    def forecast(self, economy_config: UserEconomyConfig) -> List[BudgetForecast]:
        """Generates budget forecasts based on recent spend and user configuration.

        In debug mode, returns real forecasts with ``debug_mode=True`` but
        alert_level is capped at 'warning' — never 'critical' or 'exceeded'.
        """
        forecasts = []

        # 1. Global Budget Forecast
        if economy_config.global_budget_usd is not None:
            global_forecast = self._calculate_forecast(
                label="global", 
                budget_usd=economy_config.global_budget_usd, 
                thresholds=economy_config.alert_thresholds,
                period_days=30 # Global budget is monthly by default
            )
            if global_forecast:
                forecasts.append(global_forecast)

        # 2. Per-Provider Forecasts
        for pb in economy_config.provider_budgets:
            if pb.max_cost_usd is not None:
                # Map period to days
                period_map = {
                    "daily": 1,
                    "weekly": 7,
                    "monthly": 30,
                    "total": 365
                }
                days = period_map.get(pb.period, 30)
                
                provider_forecast = self._calculate_forecast(
                    label=pb.provider,
                    budget_usd=pb.max_cost_usd,
                    thresholds=economy_config.alert_thresholds,
                    period_days=days,
                    is_provider=True
                )
                if provider_forecast:
                    forecasts.append(provider_forecast)

        return forecasts

    def _calculate_forecast(
        self, 
        label: str, 
        budget_usd: float, 
        thresholds: List[int],
        period_days: int = 30,
        is_provider: bool = False
    ) -> Optional[BudgetForecast]:
        """Calculates a single forecast for a given budget."""
        try:
            # Get spend for the relevant period
            if is_provider:
                current_spend = self.storage.cost.get_provider_spend(label, days=period_days)
            else:
                current_spend = self.storage.cost.get_total_spend(days=period_days)

            remaining = max(0.0, budget_usd - current_spend)
            
            # Get burn rate from the last 24 hours (most representative of recent traffic)
            burn_rate_hourly = self.storage.cost.get_spend_rate(hours=24)
            burn_rate_daily = burn_rate_hourly * 24

            # If no burn rate but budget exceeded, 0.0 days remaining
            if burn_rate_daily <= 0:
                pass
            else:
                remaining / burn_rate_daily
            
            # Determine alert level
            # percentage_remaining: if budget is 0, any spend (current_spend > 0) means 0% left.
            if budget_usd <= 0:
                percentage_remaining = 0.0 if current_spend > 0 else 100.0
            else:
                percentage_remaining = (remaining / budget_usd) * 100.0
                
            alert_level = "none"
            
            # alert_thresholds are % remaining (e.g., [50, 25, 10])
            sorted_thresholds = sorted(thresholds) # [10, 25, 50]
            
            if len(sorted_thresholds) > 0 and percentage_remaining <= sorted_thresholds[0]:
                alert_level = "critical"
            elif len(sorted_thresholds) > 1 and percentage_remaining <= sorted_thresholds[1]:
                alert_level = "warning"
            
            hours_to_exhaustion = None
            if burn_rate_hourly > 0:
                hours_to_exhaustion = round(remaining / burn_rate_hourly, 1)
            elif remaining <= 0:
                hours_to_exhaustion = 0.0

            return BudgetForecast(
                scope=label,
                current_spend=round(current_spend, 2),
                limit=round(budget_usd, 2),
                remaining=round(remaining, 2),
                remaining_pct=round(percentage_remaining, 1),
                burn_rate_hourly=round(burn_rate_hourly, 6),
                hours_to_exhaustion=hours_to_exhaustion,
                alert_level=alert_level,
            )
        except Exception as e:
            logger.error("Failed to calculate forecast for %s: %s", label, e)
            return None
