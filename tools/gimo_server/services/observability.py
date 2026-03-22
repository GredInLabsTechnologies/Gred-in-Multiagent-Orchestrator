from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..config import OPS_DATA_DIR
from ..ops_models import AgentActionEvent, AgentInsight


logger = logging.getLogger("orchestrator.observability")


class ObservabilityService:
    """Unified service for distributed tracing, telemetry, and agent behavior analysis."""

    AI_USAGE_LOG_PATH: Path = OPS_DATA_DIR / "logs" / "ai_usage.jsonl"
    _ui_spans = deque(maxlen=5000)
    _metrics = {
        "workflows_total": 0,
        "nodes_total": 0,
        "nodes_failed": 0,
        "tokens_total": 0,
        "cost_total_usd": 0.0,
    }

    @classmethod
    def record_usage(cls, data: Dict[str, Any]) -> None:
        """Records AI model usage for auditing."""
        data["ts"] = datetime.now(timezone.utc).isoformat()
        try:
            cls.AI_USAGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with cls.AI_USAGE_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to log usage: {e}")

    # --- Agent Telemetry & Insights ---

    @classmethod
    def record_agent_action(cls, event: AgentActionEvent) -> None:
        """Logs an agent action event for behavioral analysis."""
        # In a real impl, this would go to GICS or a DB
        logger.info(f"Agent Action: {event.agent_id} -> {event.tool} ({event.outcome})")

    @classmethod
    def get_agent_insights(cls, agent_id: str) -> List[AgentInsight]:
        """Analyzes historical telemetry to provide optimization recommendations."""
        # Simulated analysis logic
        return [
            AgentInsight(
                type="PERFORMANCE",
                priority="medium",
                message=f"Agent {agent_id} has high latency on 'search' tool.",
                recommendation="Consider using a faster model for simple searches.",
                agent_id=agent_id
            )
        ]

    # --- Tracing (Lite) ---

    @classmethod
    def record_span(cls, kind: str, name: str, attributes: Dict[str, Any]) -> None:
        """Minimal span recording for UI compatibility."""
        span = {
            "kind": kind,
            "name": name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **attributes
        }
        cls._ui_spans.append(span)
        if attributes.get("status") == "failed":
            cls._metrics["nodes_failed"] += 1
        if kind == "node":
            cls._metrics["nodes_total"] += 1
            cls._metrics["tokens_total"] += attributes.get("tokens_used", 0)
            cls._metrics["cost_total_usd"] += attributes.get("cost_usd", 0.0)

    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        return dict(cls._metrics)

    @classmethod
    def list_traces(cls, limit: int = 20) -> List[Dict[str, Any]]:
        return list(cls._ui_spans)[-limit:]
    
    @classmethod
    def record_structured_event(cls, event_type: str, status: str, **kwargs) -> None:
        """Records a versioned structured event."""
        # Could also persist to a separate log file
        pass
