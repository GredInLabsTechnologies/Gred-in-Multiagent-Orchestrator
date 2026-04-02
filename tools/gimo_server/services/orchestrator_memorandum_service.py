"""OrchestratorMemorandumService — Construye el memorandum para el orquestador.

Combina:
1. SOTA estático (provider_sota_2026.json) — cómo comunicarse con cada provider
2. Insights dinámicos de GICS — fiabilidad empírica de routing

Este memorandum se inyecta en el system prompt cuando el orquestador va a:
- Crear un nuevo plan
- Desplegar nuevos agentes
- No tiene la información en contexto o la recibió hace mucho
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime, timedelta

from .agent_insight_service import AgentInsightService
from .agent_telemetry_service import AgentTelemetryService

logger = logging.getLogger("orchestrator.services.memorandum")

class OrchestratorMemorandumService:
    """Construye memorandums para el orquestador combinando SOTA + GICS."""

    # Cache del memorandum SOTA (se lee una vez y se cachea)
    _sota_cache: Optional[Dict[str, Any]] = None
    _sota_cache_time: Optional[datetime] = None
    _CACHE_TTL_HOURS = 24  # Renovar cache diariamente

    @classmethod
    def _load_sota_data(cls) -> Dict[str, Any]:
        """Carga el memorandum SOTA desde provider_sota_2026.json."""
        now = datetime.now()

        # Usar cache si es reciente
        if cls._sota_cache and cls._sota_cache_time:
            age = now - cls._sota_cache_time
            if age < timedelta(hours=cls._CACHE_TTL_HOURS):
                return cls._sota_cache

        # Cargar desde disco
        sota_path = Path(__file__).parent.parent / "data" / "provider_sota_2026.json"
        try:
            with open(sota_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                cls._sota_cache = data
                cls._sota_cache_time = now
                logger.info("Loaded SOTA memorandum from %s", sota_path)
                return data
        except Exception as exc:
            logger.error("Failed to load SOTA data from %s: %s", sota_path, exc)
            return {}

    @classmethod
    def _format_sota_for_prompt(cls, sota_data: Dict[str, Any]) -> str:
        """Formatea los datos SOTA para incluirlos en el system prompt."""
        if not sota_data or "providers" not in sota_data:
            return ""

        lines = [
            "## PROVIDER COMMUNICATION GUIDELINES (SOTA 2026-04)",
            "",
            "The following providers are available with their optimal communication patterns:",
            ""
        ]

        providers = sota_data.get("providers", {})
        for provider_id, info in providers.items():
            display_name = info.get("display_name", provider_id)
            intelligence = info.get("intelligence_index", "?")

            lines.append(f"### {display_name} ({provider_id})")
            lines.append(f"Intelligence Index: {intelligence}/100")

            # Strengths
            strengths = info.get("strengths", [])
            if strengths:
                lines.append("**Strengths:**")
                for s in strengths[:3]:  # Top 3 para no saturar
                    lines.append(f"  - {s}")

            # Prompting strategy
            strategy = info.get("prompting_strategy", {})
            if strategy:
                key_principle = strategy.get("key_principle", "")
                if key_principle:
                    lines.append(f"**Key Principle:** {key_principle}")

            # Structured output method
            structured = info.get("structured_output", {})
            if structured:
                method = structured.get("method", "")
                reliability = structured.get("reliability", 0)
                lines.append(f"**Structured Output:** {method} ({reliability}% reliability)")

            # Optimal for
            optimal = info.get("optimal_for", [])
            if optimal:
                lines.append("**Optimal for:**")
                for o in optimal[:2]:  # Top 2
                    lines.append(f"  - {o}")

            lines.append("")  # Blank line between providers

        # Decision framework
        framework = sota_data.get("decision_framework", {})
        if framework:
            lines.append("## DECISION FRAMEWORK")
            lines.append("")
            lines.append("Consider these factors when choosing providers:")
            factors = framework.get("factors_to_consider", [])
            for factor in factors[:4]:  # Top 4 factores
                factor_name = factor.get("factor", "")
                insight = factor.get("insight", "")
                if factor_name and insight:
                    lines.append(f"- **{factor_name}**: {insight}")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def _get_gics_insights(cls) -> str:
        """Consulta GICS para obtener insights de fiabilidad de agentes."""
        try:
            telemetry = AgentTelemetryService()
            insight_service = AgentInsightService(telemetry)

            # Obtener patrones de fallos detectados
            patterns = insight_service.detect_patterns(limit=500)

            if not patterns:
                return "## GICS ROUTING INSIGHTS\n\nNo reliability issues detected. All agents performing nominally.\n"

            lines = [
                "## GICS ROUTING INSIGHTS",
                "",
                "The following agents have shown reliability issues in recent executions:",
                ""
            ]

            # Reportar solo los top 3 patrones más críticos
            for pattern in patterns[:3]:
                agent_id = pattern.get("agent_id", "unknown")
                agent_role = pattern.get("agent_role", "unknown")
                failure_rate = pattern.get("failure_rate", 0) * 100
                tool = pattern.get("tool", "N/A")
                severity = pattern.get("severity", "medium")

                emoji = "🔴" if severity == "high" else "🟡"
                lines.append(f"{emoji} **{agent_role}** ({agent_id})")
                lines.append(f"   - Failure rate: {failure_rate:.1f}%")
                lines.append(f"   - Tool: {tool}")
                lines.append(f"   - Severity: {severity}")
                lines.append("")

            lines.append("**Recommendation:** Prefer agents with lower failure rates unless specific capabilities are required.")
            lines.append("")

            return "\n".join(lines)

        except Exception as exc:
            logger.warning("Failed to fetch GICS insights: %s", exc)
            return "## GICS ROUTING INSIGHTS\n\n(Unable to fetch insights at this time)\n"

    @classmethod
    def build_memorandum(cls, *, include_gics: bool = True) -> str:
        """Construye el memorandum completo para el orquestador.

        Args:
            include_gics: Si incluir insights dinámicos de GICS (default: True)

        Returns:
            Memorandum formateado para incluir en el system prompt
        """
        parts = []

        # 1. SOTA estático
        sota_data = cls._load_sota_data()
        sota_section = cls._format_sota_for_prompt(sota_data)
        if sota_section:
            parts.append(sota_section)

        # 2. Insights dinámicos de GICS
        if include_gics:
            gics_section = cls._get_gics_insights()
            if gics_section:
                parts.append(gics_section)

        if not parts:
            return ""

        # Encabezado
        header = [
            "=" * 80,
            "ORCHESTRATOR MEMORANDUM",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 80,
            "",
        ]

        return "\n".join(header + parts)
