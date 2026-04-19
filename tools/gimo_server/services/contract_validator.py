"""ContractValidator — Runtime validation of GIMO contracts.

Validates Pydantic models at runtime to catch schema violations and inconsistencies.
"""
from __future__ import annotations

import logging
from typing import List, TYPE_CHECKING

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from ..models.plan import PlanNode

logger = logging.getLogger("orchestrator.contract_validator")


class ContractViolation(Exception):
    """Raised when a contract is violated at runtime."""

    def __init__(self, contract: str, field: str, message: str, severity: str = "ERROR"):
        self.contract = contract
        self.field = field
        self.message = message
        self.severity = severity
        super().__init__(f"{severity}: {contract}.{field}: {message}")


class ContractValidator:
    """Validates GIMO contracts at runtime."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"

    @classmethod
    def validate(cls, instance: BaseModel, strict: bool = False) -> List[ContractViolation]:
        """Validate a Pydantic model instance.

        Args:
            instance: Pydantic model to validate
            strict: If True, raise on first violation

        Returns:
            List of violations found

        Raises:
            ContractViolation: If strict=True and violation found
        """
        violations = []
        contract_name = instance.__class__.__name__

        # Pydantic v2 validation
        try:
            instance.model_validate(instance.model_dump())
        except ValidationError as e:
            for error in e.errors():
                field = ".".join(str(x) for x in error["loc"])
                violation = ContractViolation(
                    contract=contract_name,
                    field=field,
                    message=error["msg"],
                    severity=cls.ERROR,
                )
                violations.append(violation)
                if strict:
                    raise violation

        # Custom validations per contract type
        if contract_name == "PlanNode":
            violations.extend(cls._validate_plan_node(instance, strict))
        elif contract_name == "RoutingDecision":
            violations.extend(cls._validate_routing_decision(instance, strict))

        return violations

    @classmethod
    def _validate_plan_node(cls, node, strict: bool) -> List[ContractViolation]:
        """Validate PlanNode invariants.

        Checks:
        - routing_decision exists for v2.0 nodes
        - routing_decision.profile exists
        - No schema drift between routing_decision and legacy fields
        """
        violations = []

        # Check v2.0 nodes have routing_decision
        if node.schema_version == "2.0" and not node.routing_decision:
            violations.append(ContractViolation(
                "PlanNode", "routing_decision",
                f"v2.0 node {node.id} must have routing_decision", cls.ERROR
            ))

        # Check routing_decision has profile
        if node.routing_decision:
            if not node.routing_decision.profile:
                violations.append(ContractViolation(
                    "PlanNode", "routing_decision.profile",
                    f"routing_decision must have profile in node {node.id}", cls.ERROR
                ))

            # Check for schema drift (legacy fields contradicting routing_decision)
            model_value = getattr(node, '_model_value', {})
            if model_value.get('agent_preset'):
                legacy_preset = model_value['agent_preset']
                canonical_preset = node.routing_decision.profile.agent_preset
                if legacy_preset != canonical_preset:
                    violations.append(ContractViolation(
                        "PlanNode", "agent_preset",
                        f"Schema drift: legacy agent_preset={legacy_preset} != routing_decision.profile.agent_preset={canonical_preset}",
                        cls.WARNING
                    ))

        if strict and any(v.severity == cls.ERROR for v in violations):
            raise violations[0]

        return violations

    @classmethod
    def _validate_routing_decision(cls, decision, strict: bool) -> List[ContractViolation]:
        """Validate RoutingDecision invariants.

        Checks:
        - schema_version is 2.0
        - profile exists
        - binding exists
        - candidate_count >= 1
        """
        violations = []

        if decision.schema_version != "2.0":
            violations.append(ContractViolation(
                "RoutingDecision", "schema_version",
                f"Expected schema_version=2.0, got {decision.schema_version}", cls.WARNING
            ))

        if not decision.profile:
            violations.append(ContractViolation(
                "RoutingDecision", "profile",
                "RoutingDecision must have profile", cls.ERROR
            ))

        if not decision.binding:
            violations.append(ContractViolation(
                "RoutingDecision", "binding",
                "RoutingDecision must have binding", cls.ERROR
            ))

        if decision.candidate_count < 1:
            violations.append(ContractViolation(
                "RoutingDecision", "candidate_count",
                f"candidate_count must be >= 1, got {decision.candidate_count}", cls.ERROR
            ))

        if strict and any(v.severity == cls.ERROR for v in violations):
            raise violations[0]

        return violations

    @classmethod
    def validate_contract_consistency(cls, node: "PlanNode") -> List[ContractViolation]:
        """Validate consistency between node and its routing_decision.

        This is a higher-level check that ensures the node's contract
        is internally consistent.

        Args:
            node: PlanNode to validate

        Returns:
            List of violations
        """
        violations = []

        if not node.routing_decision:
            return violations  # Can't check consistency without routing_decision

        # Validate accessors return expected values
        binding = node.get_binding()
        profile = node.get_profile()

        if binding.provider != node.routing_decision.binding.provider:
            violations.append(ContractViolation(
                "PlanNode", "get_binding()",
                f"get_binding().provider inconsistent: {binding.provider} != {node.routing_decision.binding.provider}",
                cls.ERROR
            ))

        if profile and profile.agent_preset != node.routing_decision.profile.agent_preset:
            violations.append(ContractViolation(
                "PlanNode", "get_profile()",
                f"get_profile().agent_preset inconsistent: {profile.agent_preset} != {node.routing_decision.profile.agent_preset}",
                cls.ERROR
            ))

        return violations
