from __future__ import annotations

from typing import Protocol

from .models import DetectedIntent, ExecutionPlanDraft, SecurityDecision


class IntentEngine(Protocol):
    def detect_intent(self, input_text: str, context: dict) -> DetectedIntent:
        ...


class SecurityGuard(Protocol):
    def evaluate(self, input_text: str, context: dict) -> SecurityDecision:
        ...


class DirectResponseEngine(Protocol):
    def can_bypass_llm(self, intent: DetectedIntent, context: dict) -> bool:
        ...

    def build_execution_plan(self, intent: DetectedIntent, context: dict) -> ExecutionPlanDraft:
        ...
