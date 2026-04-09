"""Tests for RiskGate stage."""
from __future__ import annotations
import pytest
from tools.gimo_server.engine.contracts import StageInput, StageOutput
from tools.gimo_server.engine.stages.risk_gate import RiskGate
from tools.gimo_server.engine.risk_calibrator import RiskCalibrator, RiskThresholds


@pytest.fixture
def gate():
    return RiskGate()


def _make_input(risk_score: float = 10.0, intent_effective: str = "SAFE_REFACTOR") -> StageInput:
    return StageInput(
        run_id="run-risk-001",
        context={},
        artifacts={
            "intent_audit": {
                "intent_effective": intent_effective,
                "risk_score": risk_score,
            }
        },
    )


@pytest.mark.asyncio
async def test_low_risk_continues(gate):
    result = await gate.execute(_make_input(risk_score=5.0))
    assert result.status == "continue"
    assert result.artifacts["execution_decision"] == "AUTO_RUN_ELIGIBLE"


@pytest.mark.asyncio
async def test_medium_risk_halts(gate):
    """Risk between auto_run_max (30) and review_max (60) should halt for human review."""
    result = await gate.execute(_make_input(risk_score=45.0))
    assert result.status == "halt"
    assert result.artifacts["execution_decision"] == "HUMAN_APPROVAL_REQUIRED"


@pytest.mark.asyncio
async def test_medium_risk_continues_after_human_approval(gate):
    inp = _make_input(risk_score=45.0)
    inp.context["human_approval_granted"] = True

    result = await gate.execute(inp)

    assert result.status == "continue"
    assert result.artifacts["execution_decision"] == "AUTO_RUN_ELIGIBLE"
    assert result.artifacts["human_approval_granted"] is True


@pytest.mark.asyncio
async def test_high_risk_fails(gate):
    """Risk above review_max (60) should fail."""
    result = await gate.execute(_make_input(risk_score=75.0))
    assert result.status == "fail"
    assert result.artifacts["execution_decision"] == "RISK_SCORE_TOO_HIGH"


@pytest.mark.asyncio
async def test_boundary_at_auto_run_max(gate):
    """Risk exactly at auto_run_max (30) should still continue."""
    result = await gate.execute(_make_input(risk_score=30.0))
    assert result.status == "continue"


@pytest.mark.asyncio
async def test_boundary_above_auto_run_max(gate):
    """Risk just above auto_run_max should halt."""
    result = await gate.execute(_make_input(risk_score=30.1))
    assert result.status == "halt"


@pytest.mark.asyncio
async def test_custom_calibrator():
    """RiskGate with a custom calibrator that tightens thresholds."""
    class TightCalibrator(RiskCalibrator):
        def calibrated_thresholds(self, intent_class: str) -> RiskThresholds:
            return RiskThresholds(auto_run_max=10.0, review_max=20.0)

    gate = RiskGate(calibrator=TightCalibrator())
    result = await gate.execute(_make_input(risk_score=15.0))
    assert result.status == "halt"


@pytest.mark.asyncio
async def test_rollback_is_noop(gate):
    inp = _make_input()
    await gate.rollback(inp)  # Should not raise
