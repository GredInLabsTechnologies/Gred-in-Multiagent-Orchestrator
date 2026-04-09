"""Operator-class downstream effect parity (R20-001).

Asserts that ``IntentClassificationService.evaluate`` honours the
``operator_class`` discriminator on the medium-risk fallback path.

The previous parity test (``test_operator_class_parity.py``) only
covers persistence of the field on the draft. This test exercises the
actual downstream branching: same inputs, two operator classes, two
distinct execution decisions.
"""
from __future__ import annotations

from tools.gimo_server.services.intent_classification_service import (
    IntentClassificationService,
)


_BASE = dict(
    intent_declared="BUG_FIX",
    path_scope=["src/foo.py"],
    risk_score=10.0,
    policy_decision="allow",
    policy_status_code="OK",
)


def test_human_ui_falls_through_to_human_review():
    audit = IntentClassificationService.evaluate(**_BASE, operator_class="human_ui")
    assert audit.execution_decision == "HUMAN_APPROVAL_REQUIRED"
    assert "fallback_to_most_restrictive_human_review" in audit.decision_reason


def test_cognitive_agent_autoruns_same_inputs():
    audit = IntentClassificationService.evaluate(
        **_BASE, operator_class="cognitive_agent"
    )
    assert audit.execution_decision == "AUTO_RUN_ELIGIBLE"
    assert "cognitive_agent_operator_autorun_eligible" in audit.decision_reason


def test_cognitive_agent_does_not_bypass_high_risk():
    """Whitelist must NOT short-circuit the deny / high-risk gates."""
    audit = IntentClassificationService.evaluate(
        intent_declared="BUG_FIX",
        path_scope=["src/foo.py"],
        risk_score=85.0,
        policy_decision="allow",
        policy_status_code="OK",
        operator_class="cognitive_agent",
    )
    assert audit.execution_decision == "RISK_SCORE_TOO_HIGH"


def test_cognitive_agent_does_not_bypass_policy_deny():
    audit = IntentClassificationService.evaluate(
        intent_declared="BUG_FIX",
        path_scope=["/etc/passwd"],
        risk_score=10.0,
        policy_decision="deny",
        policy_status_code="DRAFT_REJECTED_FORBIDDEN_SCOPE",
        operator_class="cognitive_agent",
    )
    assert audit.execution_decision == "DRAFT_REJECTED_FORBIDDEN_SCOPE"
