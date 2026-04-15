from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from .agent_telemetry_service import AgentTelemetryService
from ..ops_models import AgentInsight
from ..utils.debug_mode import is_debug_mode

logger = logging.getLogger("orchestrator.services.insights")


class AgentInsightService:
    """Service to detect failure patterns and provide recommendations for agent governance.

    Debug mode scaffold — insight detection stays active but patterns
    are tagged with debug_mode=True so governance doesn't act on
    development noise.  Activate via DEBUG=true env var.
    """

    @property
    def debug_mode(self) -> bool:
        return is_debug_mode()

    def __init__(self, telemetry: AgentTelemetryService):
        self.telemetry = telemetry

    def detect_patterns(self, *, agent_id: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        """Identify combinations of (agent, tool, channel) with high failure rates."""
        events = self.telemetry.list_events(agent_id=agent_id, limit=limit)
        if not events:
            return []

        # Count outcomes for each combination
        # key: (agent_id, agent_role, channel, tool)
        stats: Dict[Tuple[str, str, str, Optional[str]], Dict[str, int]] = defaultdict(lambda: {"total": 0, "error": 0, "rejected": 0, "timeout": 0})
        
        for e in events:
            key = (e.agent_id, e.agent_role, e.channel, e.tool)
            stats[key]["total"] += 1
            if e.outcome == "error":
                stats[key]["error"] += 1
            elif e.outcome == "rejected":
                stats[key]["rejected"] += 1
            elif e.outcome == "timeout":
                stats[key]["timeout"] += 1

        patterns = []
        for key, counts in stats.items():
            total = counts["total"]
            if total < 3: # Need at least 3 samples to call it a pattern
                continue
                
            error_rate = (counts["error"] + counts["timeout"]) / total
            if error_rate > 0.3: # Higher than 30% failure rate
                patterns.append({
                    "agent_id": key[0],
                    "agent_role": key[1],
                    "channel": key[2],
                    "tool": key[3],
                    "total_samples": total,
                    "failure_rate": round(error_rate, 2),
                    "error_count": counts["error"],
                    "timeout_count": counts["timeout"],
                    "rejection_count": counts["rejected"],
                    "severity": "high" if error_rate > 0.7 else "medium"
                })

        # Sort by failure rate descending
        patterns.sort(key=lambda p: p["failure_rate"], reverse=True)
        return patterns

    def get_recommendations(self, *, agent_id: Optional[str] = None) -> List[AgentInsight]:
        """Generate actionable recommendations based on detected patterns."""
        patterns = self.detect_patterns(agent_id=agent_id)
        recs = []

        for p in patterns:
            # High failure rate on a specific tool
            if p["failure_rate"] > 0.5:
                if p["timeout_count"] > (p["total_samples"] * 0.4):
                    tool_name = p['tool']
                    agent_name = p['agent_id']
                    channel_name = p['channel']
                    recs.append(AgentInsight(
                        type="CONFIG_ADJUSTMENT",
                        priority="high",
                        message=f"Tool '{tool_name}' is timing out frequently for agent '{agent_name}' on channel '{channel_name}'.",
                        recommendation="Increase timeout settings or check connectivity for this channel.",
                        agent_id=agent_name,
                        tool=tool_name
                    ))
                else:
                    agent_name = p['agent_id']
                    tool_name = p['tool']
                    recs.append(AgentInsight(
                        type="POLICY_DEGRADATION",
                        priority="medium",
                        message=f"Agent '{agent_name}' has low success rate with tool '{tool_name}'.",
                        recommendation="Lower authority level for this tool or require human-in-the-loop (HITL) review.",
                        agent_id=agent_name,
                        tool=tool_name
                    ))
            
            # High rejection rate
            if p["rejection_count"] > (p["total_samples"] * 0.3):
                 agent_id_val = p["agent_id"]
                 channel_name = p["channel"]
                 recs.append(AgentInsight(
                    type="POLICY_ADJUSTMENT",
                    priority="low",
                    message=f"High rejection rate for agent '{agent_id_val}' on channel '{channel_name}'.",
                    recommendation="Evaluate if current policies are too restrictive or if agent prompts need alignment.",
                    agent_id=agent_id_val
                ))

        return recs
