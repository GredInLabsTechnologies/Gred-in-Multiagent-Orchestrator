from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .provider import ProviderRoleBinding

TaskRole = Literal["orchestrator", "executor", "researcher", "reviewer", "tool", "human_gate"]
MoodName = Literal["neutral", "assertive", "calm", "analytical", "exploratory", "cautious", "collaborative", "didactic"]
ExecutionPolicyName = Literal[
    "read_only",
    "docs_research",
    "propose_only",
    "workspace_safe",
    "workspace_experiment",
    "security_audit",
]
WorkflowPhase = Literal["intake", "planning", "awaiting_approval", "executing", "reviewing", "completed"]
AgentPresetName = Literal["plan_orchestrator", "researcher", "executor", "reviewer", "safety_reviewer", "human_gate"]
BindingMode = Literal["plan_time", "runtime"]
MutationMode = Literal["none", "workspace"]
RiskBand = Literal["low", "medium", "high"]
ComplexityBand = Literal["low", "medium", "high"]
ParallelismHint = Literal["serial", "parallelizable"]
SourceShape = Literal["structured_plan", "conversational_plan", "manual", "legacy", "unknown"]


class TaskFingerprintParts(BaseModel):
    task_type: str = "general"
    task_semantic: str = "general"
    artifact_kind: str = "artifact"
    mutation_mode: MutationMode = "none"
    risk_band: RiskBand = "medium"
    complexity_band: ComplexityBand = "medium"
    required_tools: List[str] = Field(default_factory=list)
    path_scope: List[str] = Field(default_factory=list)


class TaskDescriptor(BaseModel):
    task_id: str
    title: str
    description: str = ""
    task_type: str = "general"
    task_semantic: str = "general"
    artifact_kind: str = "artifact"
    mutation_mode: MutationMode = "none"
    risk_band: RiskBand = "medium"
    required_tools: List[str] = Field(default_factory=list)
    path_scope: List[str] = Field(default_factory=list)
    complexity_band: ComplexityBand = "medium"
    parallelism_hint: ParallelismHint = "serial"
    source_shape: SourceShape = "unknown"


class TaskConstraints(BaseModel):
    allowed_policies: List[ExecutionPolicyName] = Field(default_factory=list)
    allowed_binding_modes: List[BindingMode] = Field(default_factory=lambda: ["plan_time"])
    requires_human_approval: bool = False
    allowed_bindings: List[ProviderRoleBinding] = Field(default_factory=list)
    surface: str = "operator"
    workspace_mode: str = "ephemeral"
    policy_decision: str = "allow"
    policy_status_code: str = "POLICY_ALLOW"
    intent_effective: str = ""
    budget_mode: str = "standard"
    compiler_notes: List[str] = Field(default_factory=list)


class ResolvedAgentProfile(BaseModel):
    agent_preset: AgentPresetName
    task_role: TaskRole
    mood: MoodName
    execution_policy: ExecutionPolicyName
    workflow_phase: WorkflowPhase


class RoutingDecisionSummary(ResolvedAgentProfile):
    provider: str = "auto"
    model: str = "auto"


class RoutingDecision(BaseModel):
    summary: RoutingDecisionSummary
    resolved_profile: ResolvedAgentProfile
    binding_mode: BindingMode = "plan_time"
    routing_reason: str = ""
    provider: str = "auto"
    model: str = "auto"
    candidate_count: int = 0
    routing_schema_version: str = "1.0"
    profile_schema_version: str = "1.0"


class ProfileSummary(BaseModel):
    agent_preset: Optional[AgentPresetName] = None
    task_role: Optional[TaskRole] = None
    mood: Optional[MoodName] = None
    execution_policy: Optional[ExecutionPolicyName] = None
    workflow_phase: Optional[WorkflowPhase] = None
