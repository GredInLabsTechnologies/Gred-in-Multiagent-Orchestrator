from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

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
    """Legacy compatibility: extends ResolvedAgentProfile with binding info."""
    provider: str = "auto"
    model: str = "auto"


class ModelBinding(BaseModel):
    """Contract for model binding decision."""
    provider: str = Field(default="auto", description="Provider ID or 'auto'")
    model: str = Field(default="auto", description="Model ID or 'auto'")
    binding_mode: BindingMode = "plan_time"
    binding_reason: str = Field(default="auto", description="Why this binding was chosen")

    @field_validator("provider")
    @classmethod
    def validate_provider_known(cls, v: str) -> str:
        """Validate provider is known or 'auto'."""
        if v != "auto":
            # Lazy import to avoid circular dependency
            from ..services.provider_service_impl import ProviderService
            cfg = ProviderService.get_config()
            if cfg and v not in cfg.providers:
                import logging
                logging.warning(f"Unknown provider: {v}. Known: {list(cfg.providers.keys())}")
        return v


class RoutingDecision(BaseModel):
    """Output of ProfileRouterService.route() - SINGLE SOURCE OF TRUTH."""
    profile: ResolvedAgentProfile = Field(..., description="Resolved agent profile (5 core fields)")
    binding: ModelBinding = Field(..., description="Model binding decision")
    routing_reason: str = Field(..., description="Human-readable explanation of routing")
    candidate_count: int = Field(ge=1, description="Number of candidates evaluated")

    # Schema version WITH validation
    schema_version: str = Field(default="2.0", frozen=True, description="Contract version")

    @model_validator(mode="after")
    def validate_consistency(self) -> "RoutingDecision":
        """Validate internal consistency of routing decision."""
        # Ensure profile and binding are aligned
        if self.binding.binding_mode == "runtime" and self.profile.execution_policy not in ["workspace_safe", "workspace_experiment"]:
            import logging
            logging.warning(
                f"Runtime binding with restrictive policy {self.profile.execution_policy} may cause issues"
            )
        return self

    # BACKWARD COMPATIBILITY: Legacy code expects these fields
    @property
    def summary(self) -> RoutingDecisionSummary:
        """Legacy compatibility: Build summary from canonical fields."""
        return RoutingDecisionSummary(
            **self.profile.model_dump(),
            provider=self.binding.provider,
            model=self.binding.model,
        )

    @property
    def resolved_profile(self) -> ResolvedAgentProfile:
        """Legacy compatibility: Alias for profile."""
        return self.profile

    @property
    def provider(self) -> str:
        """Legacy compatibility: Access binding.provider."""
        return self.binding.provider

    @property
    def model(self) -> str:
        """Legacy compatibility: Access binding.model."""
        return self.binding.model

    @property
    def binding_mode(self) -> BindingMode:
        """Legacy compatibility: Access binding.binding_mode."""
        return self.binding.binding_mode

    # Legacy schema versions (for read compatibility only)
    @property
    def routing_schema_version(self) -> str:
        return "1.0"  # Legacy compat

    @property
    def profile_schema_version(self) -> str:
        return "1.0"  # Legacy compat


class ProfileSummary(BaseModel):
    agent_preset: Optional[AgentPresetName] = None
    task_role: Optional[TaskRole] = None
    mood: Optional[MoodName] = None
    execution_policy: Optional[ExecutionPolicyName] = None
    workflow_phase: Optional[WorkflowPhase] = None
