"""Contract tests for GIMO routing system using property-based testing."""
import pytest
from hypothesis import given, strategies as st
from pydantic import ValidationError

from tools.gimo_server.models.agent_routing import (
    RoutingDecision,
    ModelBinding,
    ResolvedAgentProfile,
    AgentPresetName,
    TaskRole,
    MoodName,
    ExecutionPolicyName,
    WorkflowPhase,
    BindingMode,
)


# Strategies for generating valid enum values
agent_presets = st.sampled_from(["plan_orchestrator", "researcher", "executor", "reviewer", "safety_reviewer", "human_gate"])
task_roles = st.sampled_from(["orchestrator", "executor", "researcher", "reviewer", "tool", "human_gate"])
moods = st.sampled_from(["neutral", "assertive", "calm", "analytical", "exploratory", "cautious", "collaborative", "didactic"])
policies = st.sampled_from(["read_only", "docs_research", "propose_only", "workspace_safe", "workspace_experiment", "security_audit"])
phases = st.sampled_from(["intake", "planning", "awaiting_approval", "executing", "reviewing", "completed"])
binding_modes = st.sampled_from(["plan_time", "runtime"])


class TestRoutingDecisionContract:
    """Contract tests for RoutingDecision v2.0."""

    def test_schema_version_is_frozen(self):
        """Schema version cannot be changed after creation."""
        profile = ResolvedAgentProfile(
            agent_preset="executor",
            task_role="executor",
            mood="assertive",
            execution_policy="workspace_safe",
            workflow_phase="executing",
        )
        binding = ModelBinding(
            provider="local_ollama",
            model="test",
            binding_mode="plan_time",
            binding_reason="test",
        )
        decision = RoutingDecision(
            profile=profile,
            binding=binding,
            routing_reason="test",
            candidate_count=1,
        )

        assert decision.schema_version == "2.0"

        # Pydantic frozen field - can't be changed
        with pytest.raises((ValidationError, TypeError)):
            decision.schema_version = "3.0"

    @given(
        preset=agent_presets,
        role=task_roles,
        mood=moods,
        policy=policies,
        phase=phases,
        provider=st.sampled_from(["auto", "local_ollama", "claude-account"]),
        model=st.text(min_size=1, max_size=50),
        candidate_count=st.integers(min_value=1, max_value=100),
    )
    def test_routing_decision_invariants(self, preset, role, mood, policy, phase, provider, model, candidate_count):
        """Property test: invariants hold for diverse inputs."""
        profile = ResolvedAgentProfile(
            agent_preset=preset,
            task_role=role,
            mood=mood,
            execution_policy=policy,
            workflow_phase=phase,
        )
        binding = ModelBinding(
            provider=provider,
            model=model,
            binding_mode="plan_time",
            binding_reason="test",
        )
        decision = RoutingDecision(
            profile=profile,
            binding=binding,
            routing_reason="test",
            candidate_count=candidate_count,
        )

        # Invariant 1: schema_version always "2.0"
        assert decision.schema_version == "2.0"

        # Invariant 2: profile matches input
        assert decision.profile.agent_preset == preset
        assert decision.profile.task_role == role
        assert decision.profile.mood == mood
        assert decision.profile.execution_policy == policy
        assert decision.profile.workflow_phase == phase

        # Invariant 3: binding matches input
        assert decision.binding.provider == provider
        assert decision.binding.model == model

        # Invariant 4: candidate_count valid
        assert decision.candidate_count >= 1

        # Invariant 5: backward compat summary is derivable
        summary = decision.summary
        assert summary.agent_preset == preset
        assert summary.provider == provider
        assert summary.model == model

        # Invariant 6: backward compat resolved_profile works
        assert decision.resolved_profile.agent_preset == preset

        # Invariant 7: backward compat flat fields work
        assert decision.provider == provider
        assert decision.model == model
        assert decision.binding_mode == "plan_time"

    def test_backward_compat_summary_is_readonly(self):
        """Summary property is read-only, cannot be set directly."""
        profile = ResolvedAgentProfile(
            agent_preset="executor",
            task_role="executor",
            mood="assertive",
            execution_policy="workspace_safe",
            workflow_phase="executing",
        )
        binding = ModelBinding(provider="auto", model="auto", binding_mode="plan_time", binding_reason="test")
        decision = RoutingDecision(profile=profile, binding=binding, routing_reason="test", candidate_count=1)

        # Should not be able to set summary
        with pytest.raises(AttributeError):
            decision.summary = None  # type: ignore

    def test_model_binding_validates_provider(self):
        """ModelBinding validates provider against known providers (warning only)."""
        # Unknown provider should log warning but not fail
        binding = ModelBinding(
            provider="unknown_provider",
            model="test",
            binding_mode="plan_time",
            binding_reason="test"
        )
        assert binding.provider == "unknown_provider"  # Warning logged, but accepted

    def test_routing_decision_validates_consistency(self):
        """RoutingDecision validator checks consistency between profile and binding."""
        profile = ResolvedAgentProfile(
            agent_preset="reviewer",
            task_role="reviewer",
            mood="cautious",
            execution_policy="read_only",  # Restrictive policy
            workflow_phase="reviewing",
        )
        binding = ModelBinding(
            provider="auto",
            model="auto",
            binding_mode="runtime",  # Runtime binding with restrictive policy
            binding_reason="test",
        )

        # Should create successfully but log warning
        decision = RoutingDecision(
            profile=profile,
            binding=binding,
            routing_reason="test",
            candidate_count=1,
        )
        assert decision is not None

    @given(
        candidate_count=st.integers(max_value=0)
    )
    def test_candidate_count_must_be_positive(self, candidate_count):
        """Candidate count must be >= 1."""
        profile = ResolvedAgentProfile(
            agent_preset="executor",
            task_role="executor",
            mood="assertive",
            execution_policy="workspace_safe",
            workflow_phase="executing",
        )
        binding = ModelBinding(provider="auto", model="auto", binding_mode="plan_time", binding_reason="test")

        with pytest.raises(ValidationError):
            RoutingDecision(
                profile=profile,
                binding=binding,
                routing_reason="test",
                candidate_count=candidate_count,
            )


class TestModelBindingContract:
    """Contract tests for ModelBinding."""

    def test_binding_mode_is_literal(self):
        """Binding mode must be one of allowed values."""
        with pytest.raises(ValidationError):
            ModelBinding(
                provider="auto",
                model="auto",
                binding_mode="invalid",  # type: ignore
                binding_reason="test",
            )

    @given(
        provider=st.text(min_size=1, max_size=50),
        model=st.text(min_size=1, max_size=50),
        mode=binding_modes,
    )
    def test_model_binding_accepts_any_text(self, provider, model, mode):
        """ModelBinding accepts any text for provider/model."""
        binding = ModelBinding(
            provider=provider,
            model=model,
            binding_mode=mode,
            binding_reason="test",
        )
        assert binding.provider == provider
        assert binding.model == model
        assert binding.binding_mode == mode


class TestResolvedAgentProfileContract:
    """Contract tests for ResolvedAgentProfile."""

    @given(
        preset=agent_presets,
        role=task_roles,
        mood=moods,
        policy=policies,
        phase=phases,
    )
    def test_resolved_profile_all_valid_combinations(self, preset, role, mood, policy, phase):
        """All valid enum combinations should work."""
        profile = ResolvedAgentProfile(
            agent_preset=preset,
            task_role=role,
            mood=mood,
            execution_policy=policy,
            workflow_phase=phase,
        )
        assert profile.agent_preset == preset
        assert profile.task_role == role
        assert profile.mood == mood
        assert profile.execution_policy == policy
        assert profile.workflow_phase == phase

    def test_invalid_preset_rejected(self):
        """Invalid preset should be rejected."""
        with pytest.raises(ValidationError):
            ResolvedAgentProfile(
                agent_preset="invalid",  # type: ignore
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            )
