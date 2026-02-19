from __future__ import annotations

from .models import DetectedIntent, ExecutionPlanDraft


class RuleBasedDirectResponseEngine:
    def can_bypass_llm(self, intent: DetectedIntent, context: dict) -> bool:
        return intent.name in {"ASK_STATUS", "HELP"}

    def build_execution_plan(self, intent: DetectedIntent, context: dict) -> ExecutionPlanDraft:
        prompt = (context.get("prompt") or "").strip()

        if intent.name == "HELP":
            return ExecutionPlanDraft(
                content=(
                    "Puedo ayudarte con: \n"
                    "- Crear planes técnicos\n"
                    "- Consultar estado de drafts/runs\n"
                    "- Guiarte para aprobar y ejecutar workflows"
                ),
                metadata={"direct_response": True, "intent": intent.name},
            )

        if intent.name == "ASK_STATUS":
            return ExecutionPlanDraft(
                content=(
                    "Estado solicitado. Revisa /ops/drafts y /ops/runs para ver pendientes, "
                    "en ejecución y completados."
                ),
                metadata={"direct_response": True, "intent": intent.name},
            )

        if intent.name == "CREATE_PLAN":
            trimmed = prompt[:500] if prompt else "(sin prompt)"
            return ExecutionPlanDraft(
                content=(
                    "PLAN PROPUESTO\n"
                    "1) Analizar objetivo y restricciones\n"
                    "2) Diseñar arquitectura y contratos\n"
                    "3) Implementar por hitos\n"
                    "4) Validar con tests\n"
                    "5) Entregar evidencia\n\n"
                    f"Contexto base: {trimmed}"
                ),
                metadata={"direct_response": False, "intent": intent.name},
            )

        return ExecutionPlanDraft(
            content="No tengo una respuesta directa para este caso.",
            metadata={"direct_response": False, "intent": intent.name},
        )
