from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .agent_routing import (
    BindingMode,
    ExecutionPolicyName,
    ResolvedAgentProfile,
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
    id: str
    label: str
    prompt: str = ""
    model: str = "auto"
    provider: str = "auto"
    role: str = "worker"
    node_type: str = "worker"
    role_definition: str = ""
    is_orchestrator: bool = False
    depends_on: List[str] = Field(default_factory=list)
    status: str = "pending"
    output: Optional[str] = None
    error: Optional[str] = None
    position: PlanNodePosition = Field(default_factory=PlanNodePosition)
    config: Dict[str, Any] = Field(default_factory=dict)
    agent_preset: Optional[str] = None
    binding_mode: BindingMode = "plan_time"
    execution_policy: Optional[ExecutionPolicyName] = None
    workflow_phase: Optional[WorkflowPhase] = None
    task_fingerprint: Optional[str] = None
    task_descriptor: Optional[TaskDescriptor] = None
    resolved_profile: Optional[ResolvedAgentProfile] = None
    routing_decision_summary: Optional[RoutingDecisionSummary] = None
    routing_reason: str = ""
    execution_hints: PlanNodeExecutionHints = Field(default_factory=PlanNodeExecutionHints)
    binding: PlanNodeBinding = Field(default_factory=PlanNodeBinding)
    routing_schema_version: str = "1.0"
    profile_schema_version: str = "1.0"


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
