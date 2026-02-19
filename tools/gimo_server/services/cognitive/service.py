from __future__ import annotations

from typing import Any, Dict, Optional

from .direct_response_engine import RuleBasedDirectResponseEngine
from .intent_engine import RuleBasedIntentEngine
from .models import CognitiveDecision, DetectedIntent
from .security_guard import RuleBasedSecurityGuard


class CognitiveService:
    def __init__(
        self,
        *,
        intent_engine: Optional[RuleBasedIntentEngine] = None,
        security_guard: Optional[RuleBasedSecurityGuard] = None,
        direct_response_engine: Optional[RuleBasedDirectResponseEngine] = None,
    ) -> None:
        self.intent_engine = intent_engine or RuleBasedIntentEngine()
        self.security_guard = security_guard or RuleBasedSecurityGuard()
        self.direct_response_engine = direct_response_engine or RuleBasedDirectResponseEngine()

    def evaluate(self, input_text: str, context: Optional[Dict[str, Any]] = None) -> CognitiveDecision:
        ctx = dict(context or {})

        security = self.security_guard.evaluate(input_text, ctx)
        if not security.allowed:
            intent = DetectedIntent(name="UNKNOWN", confidence=0.0, reason="blocked_by_security")
            return CognitiveDecision(
                intent=intent,
                security=security,
                decision_path="security_block",
                can_bypass_llm=False,
                direct_content=None,
                error_actionable="Solicitud bloqueada por seguridad. Reformula sin intentar evadir políticas.",
                context_updates={
                    "detected_intent": intent.name,
                    "decision_path": "security_block",
                    "security_flags": list(security.flags),
                    "security_reason": security.reason,
                },
            )

        intent = self.intent_engine.detect_intent(input_text, ctx)
        can_bypass = self.direct_response_engine.can_bypass_llm(intent, ctx)

        if can_bypass:
            draft = self.direct_response_engine.build_execution_plan(intent, ctx)
            return CognitiveDecision(
                intent=intent,
                security=security,
                decision_path="direct_response",
                can_bypass_llm=True,
                direct_content=draft.content,
                error_actionable=None,
                context_updates={
                    "detected_intent": intent.name,
                    "decision_path": "direct_response",
                    "security_flags": list(security.flags),
                    "cognitive_metadata": draft.metadata,
                },
            )

        return CognitiveDecision(
            intent=intent,
            security=security,
            decision_path="llm_generate",
            can_bypass_llm=False,
            direct_content=None,
            error_actionable=None,
            context_updates={
                "detected_intent": intent.name,
                "decision_path": "llm_generate",
                "security_flags": list(security.flags),
            },
        )
