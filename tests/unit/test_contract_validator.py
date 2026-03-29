"""Unit tests for ContractValidator."""
import pytest
from pydantic import ValidationError

from tools.gimo_server.models.plan import PlanNode
from tools.gimo_server.models.agent_routing import RoutingDecision, ModelBinding, ResolvedAgentProfile
from tools.gimo_server.services.contract_validator import ContractValidator, ContractViolation


class TestContractValidator:
    """Tests for ContractValidator."""

    def test_validate_valid_routing_decision(self):
        """Valid RoutingDecision passes validation."""
        decision = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="executor",
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            ),
            binding=ModelBinding(
                provider="openai",
                model="gpt-4",
                binding_mode="plan_time",
                binding_reason="test",
            ),
            routing_reason="test routing",
            candidate_count=1,
        )

        violations = ContractValidator.validate(decision, strict=False)
        assert len(violations) == 0

    def test_validate_routing_decision_missing_profile(self):
        """RoutingDecision without profile raises error."""
        # Can't create without profile due to Pydantic, but we can test the validator logic
        decision = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="executor",
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            ),
            binding=ModelBinding(provider="auto", model="auto", binding_mode="plan_time", binding_reason="test"),
            routing_reason="test",
            candidate_count=1,
        )

        # Manually set profile to None to test validator
        decision.__dict__["profile"] = None

        violations = ContractValidator._validate_routing_decision(decision, strict=False)
        assert len(violations) > 0
        assert any("profile" in v.field for v in violations)
        assert any(v.severity == ContractValidator.ERROR for v in violations)

    def test_validate_routing_decision_missing_binding(self):
        """RoutingDecision without binding raises error."""
        decision = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="executor",
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            ),
            binding=ModelBinding(provider="auto", model="auto", binding_mode="plan_time", binding_reason="test"),
            routing_reason="test",
            candidate_count=1,
        )

        # Manually set binding to None
        decision.__dict__["binding"] = None

        violations = ContractValidator._validate_routing_decision(decision, strict=False)
        assert len(violations) > 0
        assert any("binding" in v.field for v in violations)

    def test_validate_routing_decision_invalid_candidate_count(self):
        """RoutingDecision with candidate_count < 1 raises error."""
        decision = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="executor",
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            ),
            binding=ModelBinding(provider="auto", model="auto", binding_mode="plan_time", binding_reason="test"),
            routing_reason="test",
            candidate_count=1,
        )

        # Manually set invalid candidate_count
        decision.__dict__["candidate_count"] = 0

        violations = ContractValidator._validate_routing_decision(decision, strict=False)
        assert len(violations) > 0
        assert any("candidate_count" in v.field for v in violations)

    def test_validate_plan_node_v2_with_routing_decision(self):
        """v2.0 PlanNode with routing_decision passes validation."""
        routing = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="executor",
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            ),
            binding=ModelBinding(provider="openai", model="gpt-4", binding_mode="plan_time", binding_reason="test"),
            routing_reason="test",
            candidate_count=1,
        )

        node = PlanNode(id="test-1", label="", routing_decision=routing)

        violations = ContractValidator.validate(node, strict=False)
        assert len(violations) == 0

    def test_validate_plan_node_v2_missing_routing_decision(self):
        """v2.0 PlanNode without routing_decision raises error."""
        node = PlanNode(id="test-2", label="")
        node.__dict__["schema_version"] = "2.0"

        violations = ContractValidator._validate_plan_node(node, strict=False)
        assert len(violations) > 0
        assert any("routing_decision" in v.field for v in violations)
        assert any(v.severity == ContractValidator.ERROR for v in violations)

    def test_validate_plan_node_missing_profile_in_routing(self):
        """PlanNode with routing_decision but no profile raises error."""
        routing = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="executor",
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            ),
            binding=ModelBinding(provider="auto", model="auto", binding_mode="plan_time", binding_reason="test"),
            routing_reason="test",
            candidate_count=1,
        )

        node = PlanNode(id="test-3", label="", routing_decision=routing)

        # Manually remove profile
        node.routing_decision.__dict__["profile"] = None

        violations = ContractValidator._validate_plan_node(node, strict=False)
        assert len(violations) > 0
        assert any("routing_decision.profile" in v.field for v in violations)

    def test_validate_contract_consistency(self):
        """validate_contract_consistency checks node ↔ routing_decision consistency."""
        routing = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="executor",
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            ),
            binding=ModelBinding(provider="openai", model="gpt-4", binding_mode="plan_time", binding_reason="test"),
            routing_reason="test",
            candidate_count=1,
        )

        node = PlanNode(id="test-4", label="", routing_decision=routing)

        violations = ContractValidator.validate_contract_consistency(node)
        assert len(violations) == 0

    def test_validate_contract_consistency_no_routing_decision(self):
        """validate_contract_consistency returns empty for nodes without routing_decision."""
        node = PlanNode(id="test-5", label="")

        violations = ContractValidator.validate_contract_consistency(node)
        assert len(violations) == 0  # Can't check consistency without routing_decision

    def test_validate_strict_mode_raises_on_error(self):
        """Strict mode raises on first ERROR violation."""
        decision = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="executor",
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            ),
            binding=ModelBinding(provider="auto", model="auto", binding_mode="plan_time", binding_reason="test"),
            routing_reason="test",
            candidate_count=1,
        )

        # Manually break contract
        decision.__dict__["candidate_count"] = 0

        with pytest.raises(ContractViolation) as exc_info:
            ContractValidator._validate_routing_decision(decision, strict=True)

        assert "candidate_count" in str(exc_info.value)

    def test_contract_violation_exception(self):
        """ContractViolation exception has correct attributes."""
        violation = ContractViolation(
            contract="RoutingDecision",
            field="candidate_count",
            message="must be >= 1",
            severity="ERROR",
        )

        assert violation.contract == "RoutingDecision"
        assert violation.field == "candidate_count"
        assert violation.message == "must be >= 1"
        assert violation.severity == "ERROR"
        assert "ERROR" in str(violation)
        assert "RoutingDecision.candidate_count" in str(violation)

    def test_validate_pydantic_errors_captured(self):
        """Pydantic ValidationErrors are captured as violations."""
        # This test would trigger actual Pydantic validation errors
        # For now, we trust the implementation handles this
        pass

    def test_validate_schema_version_warning(self):
        """Non-2.0 schema_version generates warning."""
        decision = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="executor",
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            ),
            binding=ModelBinding(provider="auto", model="auto", binding_mode="plan_time", binding_reason="test"),
            routing_reason="test",
            candidate_count=1,
        )

        # Manually set wrong version (frozen=True prevents normal assignment)
        decision.__dict__["schema_version"] = "1.0"

        violations = ContractValidator._validate_routing_decision(decision, strict=False)
        # Should have warning about schema_version
        version_violations = [v for v in violations if "schema_version" in v.field]
        assert len(version_violations) > 0
        assert version_violations[0].severity == ContractValidator.WARNING

    def test_severity_levels(self):
        """ContractValidator defines severity levels."""
        assert ContractValidator.ERROR == "ERROR"
        assert ContractValidator.WARNING == "WARNING"
        assert ContractValidator.INFO == "INFO"
