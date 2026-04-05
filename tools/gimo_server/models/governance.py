"""Governance models for SAGP (Surface-Agnostic Governance Protocol).

These frozen dataclasses represent the output of the SAGP Gateway:
- GovernanceVerdict: result of evaluating a single action
- GovernanceSnapshot: aggregate governance state for a surface/thread
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict


@dataclass(frozen=True)
class GovernanceVerdict:
    """Immutable result of a governance evaluation.

    Returned by SagpGateway.evaluate_action() — every surface receives the
    same verdict structure regardless of transport.
    """

    allowed: bool
    policy_name: str  # Execution policy that applies
    risk_band: str  # "low" | "medium" | "high"
    trust_score: float  # 0.0–1.0
    estimated_cost_usd: float
    requires_approval: bool  # HITL needed?
    circuit_breaker_state: str  # "closed" | "open" | "half_open"
    proof_id: str  # SHA256 proof chain entry ID
    reasoning: str  # Human-readable explanation
    constraints: tuple[str, ...] = ()  # Restrictions applied

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "policy_name": self.policy_name,
            "risk_band": self.risk_band,
            "trust_score": round(self.trust_score, 4),
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "requires_approval": self.requires_approval,
            "circuit_breaker_state": self.circuit_breaker_state,
            "proof_id": self.proof_id,
            "reasoning": self.reasoning,
            "constraints": list(self.constraints),
        }


@dataclass(frozen=True)
class GovernanceSnapshot:
    """Aggregate governance state for a surface/thread at a point in time.

    Used by dashboards, MCP resources, and monitoring to give a complete
    picture of governance health.
    """

    surface_type: str
    surface_name: str
    active_policy: str
    trust_profile: Dict[str, float] = field(default_factory=dict)
    budget_status: Dict[str, Any] = field(default_factory=dict)
    gics_health: Dict[str, Any] = field(default_factory=dict)
    proof_chain_length: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface_type": self.surface_type,
            "surface_name": self.surface_name,
            "active_policy": self.active_policy,
            "trust_profile": self.trust_profile,
            "budget_status": self.budget_status,
            "gics_health": self.gics_health,
            "proof_chain_length": self.proof_chain_length,
            "timestamp": self.timestamp.isoformat(),
        }
