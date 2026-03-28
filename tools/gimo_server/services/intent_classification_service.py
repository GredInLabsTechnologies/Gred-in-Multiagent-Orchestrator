from __future__ import annotations

from typing import Iterable, List

from ..ops_models import IntentDecisionAudit


class IntentClassificationService:
    """Phase-4 intent classification and auto-run eligibility matrix."""

    _LOW_RISK_AUTORUN = {"DOC_UPDATE", "TEST_ADD", "SAFE_REFACTOR"}
    _ALWAYS_REVIEW = {"FEATURE_ADD_LOW_RISK", "ARCH_CHANGE", "SECURITY_CHANGE", "CORE_RUNTIME_CHANGE"}
    _DEFAULT_INTENT_BY_SEMANTIC = {
        "planning": "SAFE_REFACTOR",
        "research": "DOC_UPDATE",
        "security": "SAFE_REFACTOR",
        "review": "SAFE_REFACTOR",
        "approval": "ARCH_CHANGE",
        "implementation": "SAFE_REFACTOR",
    }

    _SECURITY_HINTS = (
        "tools/gimo_server/security",
        "security/",
        "auth",
        "license_guard",
        "threat",
    )
    _CORE_RUNTIME_HINTS = (
        "tools/gimo_server/services/runtime_policy_service.py",
        "tools/gimo_server/services/run_worker.py",
        "tools/gimo_server/routers/ops/run_router.py",
        "tools/gimo_server/routers/ops/plan_router.py",
        "tools/gimo_server/ops_models.py",
        "policy.json",
        "baseline_manifest.json",
        "tools/gimo_server/mcp_bridge",
    )

    @classmethod
    def _normalize_scope(cls, path_scope: Iterable[str]) -> List[str]:
        out: List[str] = []
        for value in path_scope or []:
            p = str(value or "").replace("\\", "/").strip()
            if p:
                out.append(p)
        return out

    @classmethod
    def _is_docs_only(cls, normalized_scope: List[str]) -> bool:
        if not normalized_scope:
            return True
        for p in normalized_scope:
            low = p.lower()
            if "/docs/" in f"/{low}" or low.startswith("docs/"):
                continue
            if low.endswith(".md") or low.endswith(".rst"):
                continue
            return False
        return True

    @classmethod
    def _is_tests_only(cls, normalized_scope: List[str]) -> bool:
        if not normalized_scope:
            return True
        for p in normalized_scope:
            low = p.lower()
            if "/tests/" in f"/{low}" or low.startswith("tests/"):
                continue
            if low.endswith("_test.py") or low.endswith(".test.ts") or low.endswith(".test.tsx"):
                continue
            return False
        return True

    @classmethod
    def _matches_any_hint(cls, path: str, hints: Iterable[str]) -> bool:
        low = path.lower()
        for hint in hints:
            if hint.lower() in low:
                return True
        return False

    @classmethod
    def _classify_effective_intent(cls, declared: str, normalized_scope: List[str]) -> tuple[str, List[str]]:
        reasons: List[str] = []
        effective = declared

        touches_security = any(cls._matches_any_hint(p, cls._SECURITY_HINTS) for p in normalized_scope)
        touches_core_runtime = any(cls._matches_any_hint(p, cls._CORE_RUNTIME_HINTS) for p in normalized_scope)

        if touches_core_runtime:
            effective = "CORE_RUNTIME_CHANGE"
            reasons.append("scope_touches_core_runtime")
            return effective, reasons

        if touches_security:
            effective = "SECURITY_CHANGE"
            reasons.append("scope_touches_security")
            return effective, reasons

        if declared == "DOC_UPDATE" and not cls._is_docs_only(normalized_scope):
            effective = "SAFE_REFACTOR"
            reasons.append("doc_update_scope_not_docs_only")
        elif declared == "TEST_ADD" and not cls._is_tests_only(normalized_scope):
            effective = "SAFE_REFACTOR"
            reasons.append("test_add_scope_not_tests_only")

        return effective, reasons

    @classmethod
    def default_intent_for_descriptor(cls, *, task_semantic: str, mutation_mode: str) -> str:
        semantic = str(task_semantic or "").strip().lower()
        if semantic in cls._DEFAULT_INTENT_BY_SEMANTIC:
            return cls._DEFAULT_INTENT_BY_SEMANTIC[semantic]
        if str(mutation_mode or "").strip().lower() == "none":
            return "DOC_UPDATE"
        return "SAFE_REFACTOR"

    @classmethod
    def evaluate(
        cls,
        *,
        intent_declared: str,
        path_scope: Iterable[str],
        risk_score: float,
        policy_decision: str,
        policy_status_code: str,
    ) -> IntentDecisionAudit:
        normalized_scope = cls._normalize_scope(path_scope)
        risk = float(risk_score or 0.0)
        declared = str(intent_declared or "").strip()
        reasons: List[str] = []

        if policy_decision == "deny" or policy_status_code == "DRAFT_REJECTED_FORBIDDEN_SCOPE":
            reasons.append("policy_denied_scope")
            return IntentDecisionAudit(
                intent_declared=declared,
                intent_effective=declared,
                risk_score=risk,
                decision_reason=",".join(reasons),
                execution_decision="DRAFT_REJECTED_FORBIDDEN_SCOPE",
            )

        effective, rec = cls._classify_effective_intent(declared, normalized_scope)
        reasons.extend(rec)

        if risk > 60:
            reasons.append("risk_gt_60")
            return IntentDecisionAudit(
                intent_declared=declared,
                intent_effective=effective,
                risk_score=risk,
                decision_reason=",".join(reasons),
                execution_decision="RISK_SCORE_TOO_HIGH",
            )

        if 31 <= risk <= 60:
            reasons.append("risk_between_31_and_60")
            return IntentDecisionAudit(
                intent_declared=declared,
                intent_effective=effective,
                risk_score=risk,
                decision_reason=",".join(reasons),
                execution_decision="HUMAN_APPROVAL_REQUIRED",
            )

        if effective in cls._ALWAYS_REVIEW:
            reasons.append("effective_intent_requires_human_review")
            return IntentDecisionAudit(
                intent_declared=declared,
                intent_effective=effective,
                risk_score=risk,
                decision_reason=",".join(reasons),
                execution_decision="HUMAN_APPROVAL_REQUIRED",
            )

        if effective in cls._LOW_RISK_AUTORUN:
            reasons.append("autorun_eligible_low_risk_intent")
            return IntentDecisionAudit(
                intent_declared=declared,
                intent_effective=effective,
                risk_score=risk,
                decision_reason=",".join(reasons),
                execution_decision="AUTO_RUN_ELIGIBLE",
            )

        reasons.append("fallback_to_most_restrictive_human_review")
        return IntentDecisionAudit(
            intent_declared=declared,
            intent_effective=effective,
            risk_score=risk,
            decision_reason=",".join(reasons),
            execution_decision="HUMAN_APPROVAL_REQUIRED",
        )
