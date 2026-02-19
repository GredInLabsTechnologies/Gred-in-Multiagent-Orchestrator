from __future__ import annotations

from .models import DetectedIntent


class RuleBasedIntentEngine:
    def detect_intent(self, input_text: str, context: dict) -> DetectedIntent:
        text = (input_text or "").strip().lower()

        if not text:
            return DetectedIntent(name="UNKNOWN", confidence=0.0, reason="empty_input")

        if any(k in text for k in ["help", "ayuda", "qué puedes hacer", "que puedes hacer"]):
            return DetectedIntent(name="HELP", confidence=0.9, reason="help_keyword")

        if any(k in text for k in ["status", "estado", "cómo va", "como va", "resumen"]):
            return DetectedIntent(name="ASK_STATUS", confidence=0.85, reason="status_keyword")

        if any(k in text for k in ["crea un plan", "crear plan", "plan técnico", "plan tecnico", "roadmap"]):
            return DetectedIntent(name="CREATE_PLAN", confidence=0.85, reason="plan_keyword")

        return DetectedIntent(name="UNKNOWN", confidence=0.4, reason="fallback_unknown")
