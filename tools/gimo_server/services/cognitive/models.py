from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


IntentName = Literal["CREATE_PLAN", "ASK_STATUS", "HELP", "UNKNOWN"]
DecisionPath = Literal["security_block", "direct_response", "llm_generate"]


@dataclass
class DetectedIntent:
    name: IntentName
    confidence: float = 0.5
    reason: str = ""


@dataclass
class SecurityDecision:
    allowed: bool
    risk_level: Literal["low", "medium", "high"] = "low"
    reason: str = ""
    flags: List[str] = field(default_factory=list)


@dataclass
class ExecutionPlanDraft:
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CognitiveDecision:
    intent: DetectedIntent
    security: SecurityDecision
    decision_path: DecisionPath
    can_bypass_llm: bool = False
    direct_content: Optional[str] = None
    error_actionable: Optional[str] = None
    context_updates: Dict[str, Any] = field(default_factory=dict)
