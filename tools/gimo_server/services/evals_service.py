from __future__ import annotations

from typing import Any, Dict, List

from ..ops_models import (
    EvalCaseResult,
    EvalDataset,
    EvalGateConfig,
    EvalJudgeConfig,
    EvalRunReport,
    WorkflowGraph,
)
from .graph import GraphEngine


class EvalsService:
    """Regression/evals runner for workflow graphs (Fase 4.4 MVP)."""

    @classmethod
    async def run_regression(
        cls,
        *,
        workflow: WorkflowGraph,
        dataset: EvalDataset,
        judge: EvalJudgeConfig,
        gate: EvalGateConfig,
        case_limit: int | None = None,
    ) -> EvalRunReport:
        cases = dataset.cases[: int(case_limit)] if case_limit else list(dataset.cases)
        results: List[EvalCaseResult] = []

        for case in cases:
            engine = GraphEngine(workflow)
            state = await engine.execute(initial_state=dict(case.input_state))
            actual_state = dict(state.data)

            score, reason = cls._score_case(
                expected_state=case.expected_state,
                actual_state=actual_state,
                judge=judge,
            )
            passed = score >= float(case.threshold)

            results.append(
                EvalCaseResult(
                    case_id=case.case_id,
                    passed=passed,
                    score=round(score, 4),
                    input_state=dict(case.input_state),
                    expected_state=dict(case.expected_state),
                    actual_state=cls._project_actual_state(actual_state, case.expected_state, judge),
                    reason=reason,
                )
            )

        total_cases = len(results)
        passed_cases = sum(1 for item in results if item.passed)
        failed_cases = total_cases - passed_cases
        pass_rate = (passed_cases / total_cases) if total_cases else 0.0
        avg_score = (sum(item.score for item in results) / total_cases) if total_cases else 0.0
        gate_passed = pass_rate >= gate.min_pass_rate and avg_score >= gate.min_avg_score

        return EvalRunReport(
            workflow_id=workflow.id,
            total_cases=total_cases,
            passed_cases=passed_cases,
            failed_cases=failed_cases,
            pass_rate=round(pass_rate, 4),
            avg_score=round(avg_score, 4),
            gate_passed=gate_passed,
            gate=gate,
            results=results,
        )

    @staticmethod
    def _project_actual_state(
        actual_state: Dict[str, Any],
        expected_state: Dict[str, Any],
        judge: EvalJudgeConfig,
    ) -> Dict[str, Any]:
        projected: Dict[str, Any] = {}
        for key in expected_state.keys():
            projected[key] = actual_state.get(key)

        if judge.enabled and judge.output_key:
            projected[judge.output_key] = actual_state.get(judge.output_key)

        return projected

    @staticmethod
    def _score_case(
        *,
        expected_state: Dict[str, Any],
        actual_state: Dict[str, Any],
        judge: EvalJudgeConfig,
    ) -> tuple[float, str | None]:
        if not expected_state:
            return 1.0, "no_expected_state_defined"

        matched = 0
        compared = 0
        for key, expected_value in expected_state.items():
            compared += 1
            if actual_state.get(key) == expected_value:
                matched += 1

        score = (matched / compared) if compared else 0.0
        reason = None
        if score < 1.0:
            reason = f"state_mismatch:{matched}/{compared}"

        # Optional heuristic "judge" mode for a specific output key.
        if judge.enabled and judge.output_key:
            key = judge.output_key
            if key in expected_state:
                compared += 1
                if actual_state.get(key) == expected_state.get(key):
                    matched += 1
                score = (matched / compared) if compared else score
                if score < 1.0:
                    reason = f"judge_output_mismatch:{matched}/{compared}"

        return max(0.0, min(1.0, score)), reason
