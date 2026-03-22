from __future__ import annotations
from ..contracts import StageInput, StageOutput, ExecutionStage
from ...services.runtime_policy_service import RuntimePolicyService
from ...services.intent_classification_service import IntentClassificationService

class PolicyGate(ExecutionStage):
    @property
    def name(self) -> str:
        return "policy_gate"

    async def execute(self, input: StageInput) -> StageOutput:
        # 1. Evaluate Runtime Policy
        path_scope = input.context.get("path_scope", [])
        estimated_files = input.context.get("estimated_files_changed")
        estimated_loc = input.context.get("estimated_loc_changed")
        
        policy_decision = RuntimePolicyService.evaluate_draft_policy(
            path_scope=path_scope,
            estimated_files_changed=estimated_files,
            estimated_loc_changed=estimated_loc
        )
        
        # 2. Classify Intent and determine execution strategy
        intent_declared = input.context.get("intent_declared", "SAFE_REFACTOR")
        risk_score = input.context.get("risk_score", 0.0)
        
        intent_audit = IntentClassificationService.evaluate(
            intent_declared=intent_declared,
            path_scope=path_scope,
            risk_score=risk_score,
            policy_decision=policy_decision.decision,
            policy_status_code=policy_decision.status_code
        )
        
        # Combine results
        status = "continue"
        if policy_decision.decision == "deny" or intent_audit.execution_decision == "DRAFT_REJECTED_FORBIDDEN_SCOPE":
            status = "fail"
        elif policy_decision.decision == "review" or intent_audit.execution_decision == "HUMAN_APPROVAL_REQUIRED":
            status = "halt" # Wait for approval
            
        return StageOutput(
            status=status,
            artifacts={
                "policy_decision": policy_decision.model_dump(),
                "intent_audit": intent_audit.model_dump(),
                "execution_decision": intent_audit.execution_decision
            }
        )


    async def rollback(self, input: StageInput) -> None:
        pass # No side effects to rollback
