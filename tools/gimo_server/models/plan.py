from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .agent_routing import (
    BindingMode,
    ExecutionPolicyName,
    ResolvedAgentProfile,
    RoutingDecision,
    RoutingDecisionSummary,
    TaskDescriptor,
    WorkflowPhase,
)


class PlanNodePosition(BaseModel):
    x: float = 0
    y: float = 0


class PlanNodeBinding(BaseModel):
    provider: str = "auto"
    model: str = "auto"
    binding_mode: BindingMode = "plan_time"


class PlanNodeRoutingSummary(BaseModel):
    agent_preset: Optional[str] = None
    routing_reason: str = ""
    summary: Optional[RoutingDecisionSummary] = None


class PlanNodeExecutionHints(BaseModel):
    legacy_mood: Optional[str] = None
    requested_model: Optional[str] = None
    requested_provider: Optional[str] = None
    agent_rationale: Optional[str] = None


class PlanNode(BaseModel):
    """Plan execution node - routing_decision is SINGLE SOURCE OF TRUTH (v2.0)."""

    # Core identity
    id: str
    label: str
    prompt: str = ""
    role: str = "worker"  # Legacy: derivable from routing_decision
    node_type: str = "worker"  # Legacy: derivable from routing_decision
    role_definition: str = ""
    is_orchestrator: bool = False
    depends_on: List[str] = Field(default_factory=list)

    # SINGLE SOURCE OF TRUTH for routing/profile/binding (v2.0)
    routing_decision: Optional[RoutingDecision] = Field(
        default=None,
        description="Complete routing decision (profile + binding). Single source of truth."
    )

    # Task metadata
    task_fingerprint: Optional[str] = None
    task_descriptor: Optional[TaskDescriptor] = None

    # Execution state
    status: str = "pending"
    output: Optional[str] = None
    error: Optional[str] = None

    # UI metadata
    position: PlanNodePosition = Field(default_factory=PlanNodePosition)
    config: Dict[str, Any] = Field(default_factory=dict)

    # Schema version (validated)
    schema_version: str = Field(default="2.0", frozen=True)

    # LEGACY FIELDS (v1.0 backward compatibility)
    # Kept for deserializing old persisted data.  Excluded from both
    # serialization (exclude=True) and JSON schema (json_schema_extra).
    model: Optional[str] = Field(default=None, exclude=True, json_schema_extra={"deprecated": True})
    provider: Optional[str] = Field(default=None, exclude=True, json_schema_extra={"deprecated": True})
    agent_preset: Optional[str] = Field(default=None, exclude=True, json_schema_extra={"deprecated": True})
    binding_mode: Optional[BindingMode] = Field(default=None, exclude=True, json_schema_extra={"deprecated": True})
    execution_policy: Optional[ExecutionPolicyName] = Field(default=None, exclude=True, json_schema_extra={"deprecated": True})
    workflow_phase: Optional[WorkflowPhase] = Field(default=None, exclude=True, json_schema_extra={"deprecated": True})
    resolved_profile: Optional[ResolvedAgentProfile] = Field(default=None, exclude=True, json_schema_extra={"deprecated": True})
    routing_decision_summary: Optional[RoutingDecisionSummary] = Field(default=None, exclude=True, json_schema_extra={"deprecated": True})
    routing_reason: str = Field(default="", exclude=True, json_schema_extra={"deprecated": True})
    execution_hints: PlanNodeExecutionHints = Field(default_factory=PlanNodeExecutionHints, exclude=True, json_schema_extra={"deprecated": True})
    binding: PlanNodeBinding = Field(default_factory=PlanNodeBinding, exclude=True, json_schema_extra={"deprecated": True})
    routing_schema_version: str = Field(default="1.0", exclude=True, json_schema_extra={"deprecated": True})
    profile_schema_version: str = Field(default="1.0", exclude=True, json_schema_extra={"deprecated": True})

    # ACCESSORS: Clean API for accessing routing info
    def get_binding(self) -> "PlanNodeBinding":
        """Get model binding (provider, model, mode)."""
        if self.routing_decision:
            return PlanNodeBinding(
                provider=self.routing_decision.binding.provider,
                model=self.routing_decision.binding.model,
                binding_mode=self.routing_decision.binding.binding_mode,
            )
        # Fallback to legacy fields
        return PlanNodeBinding(
            provider=self.provider or "auto",
            model=self.model or "auto",
            binding_mode=self.binding_mode or "plan_time",
        )

    def get_profile(self) -> Optional[ResolvedAgentProfile]:
        """Get resolved agent profile."""
        if self.routing_decision:
            return self.routing_decision.profile
        # Fallback to legacy fields
        return self.resolved_profile

    def get_routing_reason(self) -> str:
        """Get routing reason."""
        if self.routing_decision:
            return self.routing_decision.routing_reason
        return self.routing_reason or ""

    # VALIDATORS: Ensure consistency
    @model_validator(mode="after")
    def validate_no_redundancy(self) -> "PlanNode":
        """Warn if both routing_decision and legacy fields are present."""
        if self.routing_decision:
            legacy_fields = []
            if self.model: legacy_fields.append("model")
            if self.provider: legacy_fields.append("provider")
            if self.agent_preset: legacy_fields.append("agent_preset")
            if self.execution_policy: legacy_fields.append("execution_policy")

            if legacy_fields:
                import logging
                logging.warning(
                    f"PlanNode {self.id}: Legacy fields {legacy_fields} present alongside routing_decision. "
                    f"Legacy fields ignored. Deprecated in v3.0."
                )
        return self


class PlanEdge(BaseModel):
    id: str
    source: str
    target: str


class CustomPlan(BaseModel):
    id: str
    name: str
    description: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)
    nodes: List[PlanNode] = Field(default_factory=list)
    edges: List[PlanEdge] = Field(default_factory=list)
    status: str = "draft"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_log: List[Dict[str, Any]] = Field(default_factory=list)


class CreatePlanRequest(BaseModel):
    name: str
    description: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)
    nodes: List[PlanNode] = Field(default_factory=list)
    edges: List[PlanEdge] = Field(default_factory=list)


class UpdatePlanRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[List[PlanNode]] = None
    edges: Optional[List[PlanEdge]] = None
