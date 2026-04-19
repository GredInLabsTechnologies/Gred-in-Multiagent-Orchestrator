"""Fail-closed policy contract tests for MergeGateService (OWASP ASI02).

These tests enforce the invariant declared in SYSTEM.md §2.4 and AGENTS.md:
no execution path may degrade to "allow" on error. When policy_decision is
absent from context, the merge gate MUST re-evaluate via RuntimePolicyService
rather than default to allow.

Regression guard for: audit finding F1 (merge gate policy bypass).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from tools.gimo_server.services.merge_gate_service import MergeGateService
from tools.gimo_server.ops_models import PolicyDecision


def _run_stub(run_id: str = "r_test") -> SimpleNamespace:
    """Minimal OpsRun stub with the attributes MergeGateService reads."""
    return SimpleNamespace(id=run_id, policy_decision_id="", risk_score=0.0)


def test_missing_decision_id_low_risk_intent_reevaluates_not_autoallow():
    """LOW_RISK intent without decision_id must re-evaluate, not default to allow.

    This is the exact bypass surfaced by audit F1 — the old code defaulted to
    policy_decision = "allow" for low-risk intents with missing decision_id.
    """
    context = {
        "intent_effective": "DOC_UPDATE",  # LOW_RISK
        "policy_decision_id": "",
        "policy_decision": "",
        "path_scope": ["docs/README.md"],
    }

    fake_decision = PolicyDecision(
        policy_decision_id="evald_deadbeef",
        decision="allow",
        status_code="POLICY_ALLOW",
        policy_hash_expected="expected",
        policy_hash_runtime="expected",
        triggered_rules=[],
    )

    with patch(
        "tools.gimo_server.services.runtime_policy_service.RuntimePolicyService.evaluate_draft_policy",
        return_value=fake_decision,
    ) as mock_eval, patch(
        "tools.gimo_server.services.merge_gate_service.OpsService.append_log"
    ):
        result = MergeGateService._validate_policy("r1", context, _run_stub("r1"))

    assert result is True
    mock_eval.assert_called_once()
    # path_scope propagated to re-evaluation
    kwargs = mock_eval.call_args.kwargs
    assert kwargs["path_scope"] == ["docs/README.md"]


def test_missing_decision_id_low_risk_reevaluation_returns_deny_blocks_run():
    """Re-evaluation that returns deny must block the run, not allow it."""
    context = {
        "intent_effective": "DOC_UPDATE",
        "policy_decision_id": "",
        "policy_decision": "",
        "path_scope": ["secrets/credentials.json"],
    }

    fake_decision = PolicyDecision(
        policy_decision_id="evald_deny",
        decision="deny",
        status_code="DRAFT_REJECTED_FORBIDDEN_SCOPE",
        policy_hash_expected="expected",
        policy_hash_runtime="expected",
        triggered_rules=["forbidden_path:secrets/credentials.json"],
    )

    with patch(
        "tools.gimo_server.services.runtime_policy_service.RuntimePolicyService.evaluate_draft_policy",
        return_value=fake_decision,
    ), patch(
        "tools.gimo_server.services.merge_gate_service.OpsService.append_log"
    ), patch(
        "tools.gimo_server.services.merge_gate_service.OpsService.update_run_status"
    ) as mock_status:
        result = MergeGateService._validate_policy("r2", context, _run_stub("r2"))

    assert result is False
    mock_status.assert_called_once()
    # The deny path sets WORKER_CRASHED_RECOVERABLE (existing contract at line 107)
    args, _ = mock_status.call_args
    assert args[1] == "WORKER_CRASHED_RECOVERABLE"


def test_missing_decision_reevaluation_exception_fails_closed():
    """If RuntimePolicyService raises, the gate MUST fail-closed (block), never allow."""
    context = {
        "intent_effective": "DOC_UPDATE",
        "policy_decision_id": "",
        "policy_decision": "",
        "path_scope": ["docs/x.md"],
    }

    with patch(
        "tools.gimo_server.services.runtime_policy_service.RuntimePolicyService.evaluate_draft_policy",
        side_effect=RuntimeError("policy service unreachable"),
    ), patch(
        "tools.gimo_server.services.merge_gate_service.OpsService.update_run_status"
    ) as mock_status:
        result = MergeGateService._validate_policy("r3", context, _run_stub("r3"))

    assert result is False
    mock_status.assert_called_once()
    args, _ = mock_status.call_args
    assert args[1] == "WORKER_CRASHED_RECOVERABLE"


def test_decision_id_present_but_decision_empty_reevaluates_not_autoallow():
    """Second fail-open path: decision_id set but decision value empty — must re-evaluate."""
    run = SimpleNamespace(id="r4", policy_decision_id="upstream_id_xyz", risk_score=0.0)
    context = {
        "policy_decision_id": "upstream_id_xyz",
        "policy_decision": "",  # empty — historical bug defaulted to "allow"
        "path_scope": ["src/foo.py"],
    }

    fake_decision = PolicyDecision(
        policy_decision_id="evald_xyz",
        decision="allow",
        status_code="POLICY_ALLOW",
        policy_hash_expected="h",
        policy_hash_runtime="h",
        triggered_rules=[],
    )

    with patch(
        "tools.gimo_server.services.runtime_policy_service.RuntimePolicyService.evaluate_draft_policy",
        return_value=fake_decision,
    ) as mock_eval, patch(
        "tools.gimo_server.services.merge_gate_service.OpsService.append_log"
    ):
        result = MergeGateService._validate_policy("r4", context, run)

    assert result is True
    mock_eval.assert_called_once()


def test_missing_decision_id_high_risk_intent_blocks_without_reevaluating():
    """High-risk intent without decision_id still blocks immediately (existing behavior preserved)."""
    context = {
        "intent_effective": "CODE_MUTATION",  # NOT in _LOW_RISK_INTENTS
        "policy_decision_id": "",
        "policy_decision": "",
    }

    with patch(
        "tools.gimo_server.services.runtime_policy_service.RuntimePolicyService.evaluate_draft_policy",
    ) as mock_eval, patch(
        "tools.gimo_server.services.merge_gate_service.OpsService.update_run_status"
    ) as mock_status:
        result = MergeGateService._validate_policy("r5", context, _run_stub("r5"))

    assert result is False
    mock_eval.assert_not_called()  # high-risk bypasses re-eval and blocks
    mock_status.assert_called_once()
    args, kwargs = mock_status.call_args
    assert args[1] == "WORKER_CRASHED_RECOVERABLE"


def test_valid_upstream_decision_passes_through_without_reevaluation():
    """Happy path: decision_id + decision="allow" set by upstream passes without re-eval."""
    run = SimpleNamespace(id="r6", policy_decision_id="upstream_abc", risk_score=0.0)
    context = {
        "policy_decision_id": "upstream_abc",
        "policy_decision": "allow",
        "policy_hash_expected": "h",
        "policy_hash_runtime": "h",
    }

    with patch(
        "tools.gimo_server.services.runtime_policy_service.RuntimePolicyService.evaluate_draft_policy",
    ) as mock_eval:
        result = MergeGateService._validate_policy("r6", context, run)

    assert result is True
    mock_eval.assert_not_called()
