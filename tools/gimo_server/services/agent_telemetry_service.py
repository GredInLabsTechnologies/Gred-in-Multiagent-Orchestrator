from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..ops_models import AgentActionEvent
from .gics_service import GicsService

logger = logging.getLogger("orchestrator.services.telemetry")


class AgentTelemetryService:
    """Service to persist and retrieve Agent Action Events (IDS) via GICS."""

    def __init__(self, gics: GicsService):
        self.gics = gics

    def record_event(self, event: AgentActionEvent) -> None:
        """Persist an agent action event to GICS."""
        try:
            # Key format: ae:{agent_id}:{timestamp_ms}
            # This allows prefix scanning by agent_id
            ts_ms = int(event.timestamp.timestamp() * 1000)
            key = f"ae:{event.agent_id}:{ts_ms}"
            
            # Ensure timestamp is ISO string for GICS storage if needed,
            # but AgentActionEvent.model_dump() usually handles datetime if using serializable pydantic
            data = event.model_dump()
            if isinstance(data.get("timestamp"), datetime):
                data["timestamp"] = data["timestamp"].isoformat()
                
            self.gics.put(key, data)
        except Exception as e:
            logger.error("Failed to record agent event: %s", e)

    def list_events(
        self, 
        *, 
        agent_id: Optional[str] = None, 
        limit: int = 100,
        prefix_override: Optional[str] = None
    ) -> List[AgentActionEvent]:
        """List events from GICS, optionally filtered by agent_id."""
        try:
            prefix = prefix_override or (f"ae:{agent_id}:" if agent_id else "ae:")
            items = self.gics.scan(prefix=prefix)
            
            events: List[AgentActionEvent] = []
            for item in items:
                fields = item.get("fields")
                if fields:
                    try:
                        events.append(AgentActionEvent.model_validate(fields))
                    except Exception as ve:
                        logger.warning("Failed to validate event item: %s", ve)
            
            # Sort by timestamp descending (newest first)
            events.sort(key=lambda e: e.timestamp, reverse=True)
            return events[:limit]
        except Exception as e:
            logger.error("Failed to list agent events: %s", e)
            return []

    def get_event_summary(self, agent_id: str, last_n: int = 10) -> Dict[str, Any]:
        """Get a quick summary of recent outcomes for an agent."""
        events = self.list_events(agent_id=agent_id, limit=last_n)
        if not events:
            return {"agent_id": agent_id, "count": 0}
            
        successes = sum(1 for e in events if e.outcome == "success")
        errors = sum(1 for e in events if e.outcome == "error")
        rejections = sum(1 for e in events if e.outcome == "rejected")
        
        return {
            "agent_id": agent_id,
            "count": len(events),
            "success_rate": successes / len(events) if events else 0,
            "error_count": errors,
            "rejection_count": rejections,
            "last_seen": events[0].timestamp.isoformat() if events else None
        }
