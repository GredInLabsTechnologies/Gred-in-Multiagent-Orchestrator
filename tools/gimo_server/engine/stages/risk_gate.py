from __future__ import annotations
from typing import Optional
from ..contracts import StageInput, StageOutput, ExecutionStage
from ..risk_calibrator import RiskCalibrator

class RiskGate(ExecutionStage):
    @property
    def name(self) -> str:
        return "risk_gate"

    def __init__(self, calibrator: Optional[RiskCalibrator] = None):
        self.calibrator = calibrator or RiskCalibrator()

    async def execute(self, input: StageInput) -> StageOutput:
        # R17 Cluster A.5: gates always run regardless of `approved_id`.
        # Approval is recorded in the verdict, never used to silently skip.
        human_approval_granted = bool(input.context.get("human_approval_granted"))

        # 1. Get calibrated thresholds for this intent
        intent_audit = input.artifacts.get("intent_audit", {})
        intent_effective = intent_audit.get("intent_effective", "SAFE_REFACTOR")
        
        thresholds = self.calibrator.calibrated_thresholds(intent_effective)
        
        # 2. Get current risk score
        risk_score = intent_audit.get("risk_score", 0.0)

        
        # 3. Decision logic
        status = "continue"
        execution_decision = "AUTO_RUN_ELIGIBLE"
        
        if risk_score > thresholds.review_max:
            status = "fail"
            execution_decision = "RISK_SCORE_TOO_HIGH"
        elif risk_score > thresholds.auto_run_max:
            if human_approval_granted:
                status = "continue"
            else:
                status = "halt" # Human review required
                execution_decision = "HUMAN_APPROVAL_REQUIRED"
            
        return StageOutput(
            status=status,
            artifacts={
                "risk_thresholds": thresholds.model_dump(),
                "calibrated_risk_score": risk_score,
                "execution_decision": execution_decision,
                "pre_approved": bool(input.context.get("approved_id")),
                "human_approval_granted": human_approval_granted,
            }
        )

    async def rollback(self, input: StageInput) -> None:
        """Risk gate is stateless, nothing to rollback."""
        pass

