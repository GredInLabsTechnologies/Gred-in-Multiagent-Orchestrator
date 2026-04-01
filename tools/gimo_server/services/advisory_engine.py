"""AdvisoryEngine — Calculates adaptive scores from preset telemetry.

F8.2: Scoring adaptativo que combina priors semánticos hardcodeados con telemetría
real para mejorar decisiones de routing.
"""
from __future__ import annotations

import logging
from typing import Tuple

logger = logging.getLogger("orchestrator.services.advisory_engine")


class AdvisoryEngine:
    """Calculates adaptive scores for preset ranking from telemetry.

    Combines:
    - Semantic priors (hardcoded baseline expectations)
    - Real telemetry (captured success rates, quality scores)
    - Confidence intervals (Wilson score for statistical rigor)
    - Exploration bonuses (encourage trying under-sampled presets)
    - Penalties (failure streaks, low quality)
    """

    # Thresholds for confidence
    MIN_SAMPLES_CONFIDENT = 10  # Samples mínimos para confiar en telemetría
    MIN_SAMPLES_EXPLORATION = 3  # Samples para empezar a considerar telemetría

    # Pesos para blending
    PRIOR_WEIGHT = 0.3  # Peso de prior semántico hardcodeado
    TELEMETRY_WEIGHT = 0.7  # Peso de telemetría real

    @classmethod
    def get_preset_score(
        cls,
        task_semantic: str,
        preset_name: str,
        prior_score: float = 0.0,  # Prior semántico hardcodeado
    ) -> Tuple[float, str]:
        """Calcula score adaptativo para preset en contexto semántico.

        Args:
            task_semantic: Tipo de tarea semántica ("planning", "research", etc)
            preset_name: Nombre del preset ("plan_orchestrator", "researcher", etc)
            prior_score: Score semántico hardcodeado del ProfileRouterService

        Returns:
            (score_adjustment, reason)
            score_adjustment: -0.3 a +0.3 (rango conservador)
            reason: Explicación del ajuste para observabilidad
        """
        from .preset_telemetry_service import PresetTelemetryService

        telemetry = PresetTelemetryService.get_telemetry(task_semantic, preset_name)

        if not telemetry or not isinstance(telemetry, dict):
            # Sin datos: usar prior puro
            return 0.0, f"advisory=0.00(no_telemetry,using_prior={prior_score:.2f})"

        try:
            samples = int(telemetry["samples"])
        except (KeyError, TypeError, ValueError):
            return 0.0, f"advisory=0.00(corrupt_telemetry,using_prior={prior_score:.2f})"

        if samples < cls.MIN_SAMPLES_EXPLORATION:
            # Muy pocos datos: usar prior puro + bonus exploratorio
            exploration_bonus = 0.05  # Pequeño boost para explorar
            return (
                exploration_bonus,
                f"advisory=+0.05(exploration,n={samples},prior={prior_score:.2f})",
            )

        # Calcular telemetry score
        success_rate = telemetry["success_rate"]
        avg_quality = telemetry["avg_quality_score"] / 100.0  # Normalize to 0-1
        quality_confidence = telemetry["metadata"]["quality_confidence"]

        # Blended quality score (success + quality)
        if telemetry["quality_samples"] >= 2:
            # Si tenemos quality scores, ponderar ambos
            telemetry_score = (success_rate * 0.4) + (avg_quality * 0.6)
        else:
            # Solo success_rate
            telemetry_score = success_rate

        # Confidence-based blending con prior
        if samples < cls.MIN_SAMPLES_CONFIDENT:
            # Blend prior y telemetry según confidence
            confidence_ratio = samples / cls.MIN_SAMPLES_CONFIDENT
            blended_score = (
                prior_score * (1 - confidence_ratio) + telemetry_score * confidence_ratio
            )
            blend_reason = f"blend(n={samples},conf={confidence_ratio:.2f})"
        else:
            # Suficientes samples: confiar en telemetría
            blended_score = (
                prior_score * cls.PRIOR_WEIGHT + telemetry_score * cls.TELEMETRY_WEIGHT
            )
            blend_reason = f"confident(n={samples})"

        # Convertir a adjustment score centrado en 0
        # blended_score está en [0, 1], queremos [-0.3, +0.3]
        adjustment = (blended_score - 0.5) * 0.6  # Scale to [-0.3, +0.3]

        # Aplicar penalizaciones
        failure_streak = telemetry["metadata"]["failure_streak"]
        if failure_streak >= 3:
            adjustment -= 0.15
            blend_reason += ",streak_penalty"

        # Bonus por alta calidad consistente
        if telemetry["quality_samples"] >= 5 and avg_quality >= 0.85:
            adjustment += 0.1
            blend_reason += ",quality_bonus"

        # Clamp a rango seguro
        adjustment = max(-0.3, min(0.3, adjustment))

        reason = (
            f"advisory={adjustment:+.2f}("
            f"{blend_reason},"
            f"sr={success_rate:.2f},"
            f"q={avg_quality:.2f})"
        )

        logger.debug(
            "Advisory score: semantic=%s, preset=%s, adjustment=%.3f, reason=%s",
            task_semantic,
            preset_name,
            adjustment,
            reason,
        )

        return adjustment, reason
