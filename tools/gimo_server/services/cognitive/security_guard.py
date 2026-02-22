from typing import Any, Dict

from ..cognitive.models import SecurityDecision


class RuleBasedSecurityGuard:
    """
    Lightweight pattern-matching security guard.
    Used when COGNITIVE_GIOS_BRIDGE_ENABLED=false.

    NOTE: In an orchestrator/operator context, the user IS the trusted authority.
    Phrases like 'system prompt', 'act as a', or 'ignore previous instructions' are
    legitimate architectural commands from operators.

    Only block patterns that attempt to jailbreak the LLM backend itself
    (e.g. DAN mode, unfiltered mode activations).

    A sandbox/quarantine layer for external code ingestion will be added separately.
    """

    # Minimal set — only real LLM backend jailbreak patterns.
    # NOTE: 'act as a' and 'system prompt' alone are valid operator commands.
    # 'ignore previous instructions' IS blocked because it's a canonical prompt-injection
    # attack vector, not a legitimate architectural command.
    _BLOCK_PATTERNS: tuple = (
        "jailbreak",
        "dan mode",
        "do anything now",
        "mode: unrestricted",
        "mode: enabled",
        "[dan]",
        "[jailbreak]",
        "ignore previous instructions",
        "ignore all previous instructions",
        "disregard previous instructions",
        "forget your instructions",
    )

    def evaluate(self, input_text: str, context: Dict[str, Any]) -> SecurityDecision:
        text = (input_text or "").lower()
        matched = [p for p in self._BLOCK_PATTERNS if p in text]
        if matched:
            return SecurityDecision(
                allowed=False,
                risk_level="high",
                reason="Detected blocked pattern",
                flags=matched,
            )
        return SecurityDecision(allowed=True, risk_level="low", reason="clean_input", flags=[])
