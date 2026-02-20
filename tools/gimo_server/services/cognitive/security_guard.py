from __future__ import annotations

from .models import SecurityDecision


class RuleBasedSecurityGuard:
    _BLOCK_PATTERNS = (
        "ignore previous instructions",
        "ignore all previous instructions",
        "jailbreak",
        "system prompt",
        "reveal prompt",
        "bypass safety",
    )

    def evaluate(self, input_text: str, context: dict) -> SecurityDecision:
        text = (input_text or "").lower()
        matched = [p for p in self._BLOCK_PATTERNS if p in text]
        if matched:
            return SecurityDecision(
                allowed=False,
                risk_level="high",
                reason="Detected prompt-injection/jailbreak pattern",
                flags=matched,
            )
        return SecurityDecision(allowed=True, risk_level="low", reason="clean_input", flags=[])
