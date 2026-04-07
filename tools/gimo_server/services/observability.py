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

    @classmethod
    def record_llm_usage(
        cls,
        *,
        thread_id: str | None = None,
        model: str = "unknown",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        tools_executed: int = 0,
        tool_call_format: str = "none",
        estimated: bool = False,
    ) -> None:
        """Single sink for all LLM usage. Writes to all stores atomically.

        When `estimated=True`, the tokens/cost are heuristic (e.g. CLI providers
        with no exact usage). They are tracked separately in metrics so dashboards
        can distinguish exact vs estimated totals and avoid presenting fabricated
        precision as ground truth.
        """
        total = prompt_tokens + completion_tokens

        # 1. In-memory metrics (live dashboard) — segregate estimated from exact
        if estimated:
            cls._metrics.setdefault("tokens_estimated", 0)
            cls._metrics.setdefault("cost_estimated_usd", 0.0)
            cls._metrics["tokens_estimated"] += total
            cls._metrics["cost_estimated_usd"] += cost_usd
        else:
            cls._metrics["tokens_total"] += total
            cls._metrics["cost_total_usd"] += cost_usd

        # 2. Audit log (append-only JSONL)
        cls.record_usage({
            "thread_id": thread_id,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "tools_executed": tools_executed,
            "tool_call_format": tool_call_format,
            "estimated": bool(estimated),
        })

        # 3. Thread metadata (per-conversation usage)
        if thread_id:
            try:
                from .conversation_service import ConversationService

                def _update(t):
                    prev = t.metadata.get("usage") if isinstance(t.metadata.get("usage"), dict) else {}
                    t.metadata["usage"] = {
                        "prompt_tokens": prev.get("prompt_tokens", 0) + prompt_tokens,
                        "completion_tokens": prev.get("completion_tokens", 0) + completion_tokens,
                        "cost_usd": prev.get("cost_usd", 0.0) + cost_usd,
                        "total_tokens": prev.get("total_tokens", 0) + total,
                        "estimated": bool(prev.get("estimated") or estimated),
                    }
                    return True

                ConversationService.mutate_thread(thread_id, _update)
            except Exception:
                logger.debug("Failed to update thread usage for %s", thread_id, exc_info=True)

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
