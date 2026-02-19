from __future__ import annotations

from typing import Any, Dict, Optional


class SystemPromptService:
    """Builds the master system prompt used by orchestrator and sub-agents."""

    BASE_MASTER_PROMPT = """
Eres un agente especializado de GIMO coordinado por un orquestador.

Reglas obligatorias:
1) Ejecuta SOLO la tarea asignada y respeta alcance.
2) Si falta contexto crítico, devuelve un bloqueo explícito con la información faltante.
3) Prioriza precisión, trazabilidad y pasos accionables.
4) No inventes resultados ni estados de ejecución.
5) Si hay riesgo de seguridad o conflicto, detén y reporta claramente.
6) Entrega salida estructurada, breve y verificable.
""".strip()

    @classmethod
    def build_master_prompt(
        cls,
        *,
        parent_id: Optional[str] = None,
        sub_task: Optional[str] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> str:
        constraints = constraints or {}
        extra = str(constraints.get("system_prompt") or "").strip()

        parts = [cls.BASE_MASTER_PROMPT]
        if parent_id:
            parts.append(f"Contexto de orquestación: parent_agent={parent_id}")
        if sub_task:
            parts.append(f"Tarea delegada: {sub_task}")
        if extra:
            parts.append(f"Reglas adicionales del plan:\n{extra}")

        return "\n\n".join(parts)

    @classmethod
    def compose_execution_prompt(cls, *, system_prompt: str, task: str) -> str:
        system_prompt = (system_prompt or "").strip()
        task = (task or "").strip()
        if not system_prompt:
            return task
        return f"{system_prompt}\n\n# EJECUCIÓN\n{task}"
