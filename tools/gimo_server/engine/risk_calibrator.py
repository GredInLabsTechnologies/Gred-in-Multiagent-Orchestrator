from __future__ import annotations
import logging
from typing import Any
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class RiskThresholds(BaseModel):

    auto_run_max: float
    review_max: float

def clamp(v: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, v))

class RiskCalibrator:
    """Adjusts risk thresholds based on historical success by intent class."""
    
    def __init__(self, trust_events_provider: Any = None):
        self.trust_events_provider = trust_events_provider

    def calibrated_thresholds(self, intent_class: str) -> RiskThresholds:
        # Default baseline
        baseline_auto = 30.0
        baseline_review = 60.0
        
        logger.debug(f"Calibrating thresholds for {intent_class}")

        
        if not self.trust_events_provider:
            return RiskThresholds(auto_run_max=baseline_auto, review_max=baseline_review)
            
        success_rate = self._get_historical_success_rate(intent_class)
        adjustment = (success_rate - 0.8) * 20  # +/- 20 pts around 80% baseline
        
        return RiskThresholds(
            auto_run_max=clamp(baseline_auto + adjustment, 10.0, 50.0),
            review_max=clamp(baseline_review + adjustment, 40.0, 80.0)
        )

    def _get_historical_success_rate(self, _intent_class: str) -> float:
        """Helper to fetch historical success rates for risk calibration."""
        return 0.85 # Assumed success rate for now

