"""Tests for PolicyGate stage."""
from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from tools.gimo_server.engine.contracts import StageInput, StageOutput
from tools.gimo_server.engine.stages.policy_gate import PolicyGate


class FakePolicyDecision(BaseModel):
    decision: str = "allow"
    status_code: int = 200
    reason: str = "ok"

    def model_dump(self):
        return {"decision": self.decision, "status_code": self.status_code, "reason": self.reason}


class FakeIntentAudit(BaseModel):
    execution_decision: str = "AUTO_RUN_ELIGIBLE"
    intent_effective: str = "SAFE_REFACTOR"
    risk_score: float = 10.0

    def model_dump(self):
        return {
            "execution_decision": self.execution_decision,
            "intent_effective": self.intent_effective,
            "risk_score": self.risk_score,
        }


@pytest.fixture
def gate():
    return PolicyGate()


@pytest.fixture
def base_input():
    return StageInput(
        run_id="run-001",
        context={
            "path_scope": ["src/main.py"],
            "estimated_files_changed": 1,
            "estimated_loc_changed": 10,
            "intent_declared": "SAFE_REFACTOR",
            "risk_score": 10.0,
        },
    )


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.policy_gate.IntentClassificationService")
@patch("tools.gimo_server.engine.stages.policy_gate.RuntimePolicyService")
async def test_happy_path_allow(mock_policy_svc, mock_intent_svc, gate, base_input):
    mock_policy_svc.evaluate_draft_policy.return_value = FakePolicyDecision(decision="allow")
    mock_intent_svc.evaluate.return_value = FakeIntentAudit(execution_decision="AUTO_RUN_ELIGIBLE")

    result = await gate.execute(base_input)
    assert result.status == "continue"
    assert result.artifacts["execution_decision"] == "AUTO_RUN_ELIGIBLE"


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.policy_gate.IntentClassificationService")
@patch("tools.gimo_server.engine.stages.policy_gate.RuntimePolicyService")
async def test_policy_deny_fails(mock_policy_svc, mock_intent_svc, gate, base_input):
    mock_policy_svc.evaluate_draft_policy.return_value = FakePolicyDecision(decision="deny")
    mock_intent_svc.evaluate.return_value = FakeIntentAudit(execution_decision="AUTO_RUN_ELIGIBLE")

    result = await gate.execute(base_input)
    assert result.status == "fail"


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.policy_gate.IntentClassificationService")
@patch("tools.gimo_server.engine.stages.policy_gate.RuntimePolicyService")
async def test_policy_review_halts(mock_policy_svc, mock_intent_svc, gate, base_input):
    mock_policy_svc.evaluate_draft_policy.return_value = FakePolicyDecision(decision="review")
    mock_intent_svc.evaluate.return_value = FakeIntentAudit(execution_decision="AUTO_RUN_ELIGIBLE")

    result = await gate.execute(base_input)
    assert result.status == "halt"


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.policy_gate.IntentClassificationService")
@patch("tools.gimo_server.engine.stages.policy_gate.RuntimePolicyService")
async def test_policy_review_continues_after_human_approval(mock_policy_svc, mock_intent_svc, gate, base_input):
    base_input.context["human_approval_granted"] = True
    mock_policy_svc.evaluate_draft_policy.return_value = FakePolicyDecision(decision="review")
    mock_intent_svc.evaluate.return_value = FakeIntentAudit(execution_decision="AUTO_RUN_ELIGIBLE")

    result = await gate.execute(base_input)
    assert result.status == "continue"
    assert result.artifacts["execution_decision"] == "AUTO_RUN_ELIGIBLE"
    assert result.artifacts["human_approval_granted"] is True


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.policy_gate.IntentClassificationService")
@patch("tools.gimo_server.engine.stages.policy_gate.RuntimePolicyService")
async def test_intent_forbidden_scope_fails(mock_policy_svc, mock_intent_svc, gate, base_input):
    mock_policy_svc.evaluate_draft_policy.return_value = FakePolicyDecision(decision="allow")
    mock_intent_svc.evaluate.return_value = FakeIntentAudit(
        execution_decision="DRAFT_REJECTED_FORBIDDEN_SCOPE"
    )

    result = await gate.execute(base_input)
    assert result.status == "fail"


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.policy_gate.IntentClassificationService")
@patch("tools.gimo_server.engine.stages.policy_gate.RuntimePolicyService")
async def test_intent_requires_human_approval(mock_policy_svc, mock_intent_svc, gate, base_input):
    mock_policy_svc.evaluate_draft_policy.return_value = FakePolicyDecision(decision="allow")
    mock_intent_svc.evaluate.return_value = FakeIntentAudit(
        execution_decision="HUMAN_APPROVAL_REQUIRED"
    )

    result = await gate.execute(base_input)
    assert result.status == "halt"


@pytest.mark.asyncio
async def test_rollback_is_noop(gate, base_input):
    await gate.rollback(base_input)  # Should not raise
