from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...ops_models import AgentInsight
from ..gics_service import GicsService
from ..agent_telemetry_service import AgentTelemetryService
from ..agent_insight_service import AgentInsightService

logger = logging.getLogger("orchestrator.ops")


class TelemetryMixin:
    """GICS telemetry, agent events, model priors/outcomes."""

    @classmethod
    def set_gics(cls, gics: Optional[GicsService]) -> None:
        cls._gics = gics
        if gics:
            cls._telemetry = AgentTelemetryService(gics)
            cls._insights = AgentInsightService(cls._telemetry)
        else:
            cls._telemetry = None
            cls._insights = None

    @classmethod
    def record_agent_event(cls, event: Any) -> None:
        """Record an agent action event (IDS)."""
        if not cls._telemetry:
            return
        try:
            from ...ops_models import AgentActionEvent
            if not isinstance(event, AgentActionEvent):
                event = AgentActionEvent(**event)
            cls._telemetry.record_event(event)
        except Exception as e:
            logger.error("Failed to record agent event via OpsService: %s", e)

    @classmethod
    def get_agent_insights(cls, agent_id: Optional[str] = None) -> List[AgentInsight]:
        """Get structural recommendations for agent governance."""
        if not cls._insights:
            return []
        return cls._insights.get_recommendations(agent_id=agent_id)

    @classmethod
    def seed_model_priors(
        cls,
        *,
        provider_type: str,
        model_id: str,
        prior_scores: Dict[str, float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Best-effort bridge to GICS for model prior seeding."""
        if not cls._gics:
            return None
        try:
            return cls._gics.seed_model_prior(
                provider_type=provider_type,
                model_id=model_id,
                prior_scores=prior_scores,
                metadata=metadata,
            )
        except Exception:
            return None

    @classmethod
    def record_model_outcome(
        cls,
        *,
        provider_type: str,
        model_id: str,
        success: bool,
        latency_ms: Optional[float] = None,
        cost_usd: Optional[float] = None,
        task_type: str = "general",
    ) -> Optional[Dict[str, Any]]:
        """Best-effort bridge to GICS for post-task model evidence."""
        if not cls._gics:
            return None
        try:
            return cls._gics.record_model_outcome(
                provider_type=provider_type,
                model_id=model_id,
                success=success,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                task_type=task_type,
            )
        except Exception:
            return None

    @classmethod
    def get_model_reliability(cls, *, provider_type: str, model_id: str) -> Optional[Dict[str, Any]]:
        if not cls._gics:
            return None
        try:
            return cls._gics.get_model_reliability(provider_type=provider_type, model_id=model_id)
        except Exception:
            return None

    @classmethod
    def batch_put_telemetry(cls, records: List[Dict[str, Any]], atomic: bool = False) -> Optional[Any]:
        """Write a batch of telemetry records via GICS put_many (1.3.4 primitive).

        Each record must be a dict with at least {"key": str, "value": Any}.
        Preferred over individual put() calls when flushing run-end telemetry.
        Falls back to individual puts if put_many unavailable.
        """
        if not cls._gics:
            return None
        try:
            return cls._gics.put_many(records, atomic=atomic)
        except Exception as e:
            logger.warning("batch_put_telemetry put_many failed, skipping: %s", e)
            return None

    @classmethod
    def latest_events_by_prefix(cls, prefix: str) -> Optional[Any]:
        """Return latest events for a prefix using GICS latest_by_prefix (1.3.4).

        Useful for dashboard endpoints that need the most recent event per agent/model/run.
        """
        if not cls._gics:
            return None
        try:
            return cls._gics.latest_by_prefix(prefix=prefix)
        except Exception:
            return None

    @classmethod
    def count_events_by_prefix(cls, prefix: str) -> Optional[int]:
        """Count events under a prefix using GICS count_prefix (1.3.4).

        Cheaper than scan for pure-count dashboard queries.
        """
        if not cls._gics:
            return None
        try:
            result = cls._gics.count_prefix(prefix=prefix)
            return int(result) if result is not None else None
        except Exception:
            return None

    @classmethod
    def scan_telemetry_summary(cls, prefix: str) -> Optional[Any]:
        """Inspect telemetry metadata without loading payloads via GICS scan_summary (1.3.4)."""
        if not cls._gics:
            return None
        try:
            return cls._gics.scan_summary(prefix=prefix)
        except Exception:
            return None
