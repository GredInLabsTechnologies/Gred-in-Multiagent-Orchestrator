from tools.gimo_server.services.intent_classification_service import IntentClassificationService


def test_phase4_auto_run_eligible_for_low_risk_doc_update():
    decision = IntentClassificationService.evaluate(
        intent_declared="DOC_UPDATE",
        path_scope=["docs/README.md"],
        risk_score=12,
        policy_decision="allow",
        policy_status_code="POLICY_ALLOW",
    )
    assert decision.intent_effective == "DOC_UPDATE"
    assert decision.execution_decision == "AUTO_RUN_ELIGIBLE"


def test_phase4_escalates_to_core_runtime_change_by_scope():
    decision = IntentClassificationService.evaluate(
        intent_declared="DOC_UPDATE",
        path_scope=["tools/gimo_server/services/runtime_policy_service.py"],
        risk_score=5,
        policy_decision="allow",
        policy_status_code="POLICY_ALLOW",
    )
    assert decision.intent_effective == "CORE_RUNTIME_CHANGE"
    assert decision.execution_decision == "HUMAN_APPROVAL_REQUIRED"


def test_phase4_blocks_when_risk_too_high():
    decision = IntentClassificationService.evaluate(
        intent_declared="SAFE_REFACTOR",
        path_scope=["tools/gimo_server/services/file_service.py"],
        risk_score=75,
        policy_decision="allow",
        policy_status_code="POLICY_ALLOW",
    )
    assert decision.execution_decision == "RISK_SCORE_TOO_HIGH"


def test_phase4_honors_policy_deny_before_anything_else():
    decision = IntentClassificationService.evaluate(
        intent_declared="SAFE_REFACTOR",
        path_scope=["tools/gimo_server/security/auth.py"],
        risk_score=10,
        policy_decision="deny",
        policy_status_code="DRAFT_REJECTED_FORBIDDEN_SCOPE",
    )
    assert decision.execution_decision == "DRAFT_REJECTED_FORBIDDEN_SCOPE"
