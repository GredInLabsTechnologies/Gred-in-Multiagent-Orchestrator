"""
Adaptive Timeout Service — Phase 2 of GAEP.

Predicts optimal timeouts based on historical duration data from GICS.
Uses percentile-based estimation with contextual adjustments.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("orchestrator.services.timeout.adaptive_timeout")


class AdaptiveTimeoutService:
    """Predice timeout óptimo basándose en historial de GICS."""

    # Singleton GICS instance (injected)
    _gics = None

    # Default timeouts por operación (fallback cuando no hay historial)
    DEFAULT_TIMEOUTS = {
        "plan": 180.0,
        "run": 300.0,
        "merge": 60.0,
        "recon": 120.0,
        "validate": 30.0,
    }

    # Límites absolutos (safety bounds)
    MIN_TIMEOUT = 30.0
    MAX_TIMEOUT = 600.0

    # Percentil a usar para predicción (95 = cubre 95% de casos)
    PERCENTILE = 95

    # Margen de seguridad (20% extra sobre el percentil)
    SAFETY_MARGIN = 1.2

    @classmethod
    def set_gics(cls, gics) -> None:
        """Inject GICS service instance."""
        cls._gics = gics

    @classmethod
    def _get_gics(cls):
        """Get GICS instance (None if not available)."""
        return cls._gics

    @classmethod
    def predict_timeout(
        cls,
        operation: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Predice timeout óptimo para una operación basándose en historial.

        Algorithm:
            1. Consulta GICS por ops:duration:{operation}:*
            2. Filtra por similitud de contexto (si se proporciona)
            3. Calcula percentil 95 (cubre 95% de casos históricos)
            4. Aplica ajustes contextuales (model, system load, complexity)
            5. Añade margen de seguridad (20%)
            6. Limita entre MIN_TIMEOUT y MAX_TIMEOUT

        Args:
            operation: Operation type (e.g., "plan", "run", "merge")
            context: Contextual metadata for adjustment {
                "model": str,           # Model identifier
                "system_load": str,     # "low", "medium", "high"
                "prompt_length": int,   # For plan operations
                "file_count": int,      # For run operations
                "complexity": str,      # "simple", "moderate", "complex"
            }

        Returns:
            Predicted timeout in seconds (float)
        """
        context = context or {}

        # Step 1: Get historical durations
        try:
            from .duration_telemetry_service import DurationTelemetryService

            gics = cls._get_gics()
            if gics:
                DurationTelemetryService.set_gics(gics)

            durations = DurationTelemetryService.get_historical_durations(
                operation=operation,
                context=context,
                limit=100,
            )
        except Exception as exc:
            logger.warning("Failed to fetch historical durations: %s", exc)
            durations = []

        # Step 2: Fallback to default if no history
        if not durations or len(durations) < 5:
            default = cls.DEFAULT_TIMEOUTS.get(operation, 60.0)
            logger.debug(
                "Insufficient history for %s (samples=%d), using default: %.1fs",
                operation, len(durations), default
            )
            return default

        # Step 3: Calculate percentile
        sorted_durations = sorted(durations)
        percentile_index = int(len(sorted_durations) * (cls.PERCENTILE / 100.0))
        percentile_index = min(percentile_index, len(sorted_durations) - 1)
        p95_duration = sorted_durations[percentile_index]

        logger.debug(
            "Historical durations for %s: samples=%d, p50=%.1fs, p95=%.1fs, max=%.1fs",
            operation,
            len(durations),
            sorted_durations[len(sorted_durations) // 2],
            p95_duration,
            max(durations),
        )

        # Step 4: Contextual adjustments
        adjusted = p95_duration

        # Model-based adjustment
        model = context.get("model", "").lower()
        if "opus" in model or "o1" in model:
            # Slower models need more time
            adjusted *= 1.5
            logger.debug("Adjusted +50%% for model: %s", model)
        elif "haiku" in model or "mini" in model:
            # Faster models can use less time
            adjusted *= 0.8
            logger.debug("Adjusted -20%% for model: %s", model)

        # System load adjustment
        system_load = context.get("system_load", "medium")
        if system_load == "high":
            adjusted *= 1.3
            logger.debug("Adjusted +30%% for high system load")
        elif system_load == "low":
            adjusted *= 0.9
            logger.debug("Adjusted -10%% for low system load")

        # Complexity adjustment (for plan operations)
        if operation == "plan":
            complexity = context.get("complexity", "moderate")
            if complexity == "complex":
                adjusted *= 1.4
                logger.debug("Adjusted +40%% for complex plan")
            elif complexity == "simple":
                adjusted *= 0.7
                logger.debug("Adjusted -30%% for simple plan")

            # Prompt length adjustment
            prompt_length = context.get("prompt_length", 0)
            if prompt_length > 1000:
                adjusted *= 1.2
                logger.debug("Adjusted +20%% for long prompt (%d chars)", prompt_length)

        # File count adjustment (for run operations)
        if operation == "run":
            file_count = context.get("file_count", 0)
            if file_count > 10:
                adjusted *= 1.3
                logger.debug("Adjusted +30%% for large file count (%d files)", file_count)
            elif file_count > 5:
                adjusted *= 1.15
                logger.debug("Adjusted +15%% for moderate file count (%d files)", file_count)

        # Step 5: Apply safety margin
        recommended = adjusted * cls.SAFETY_MARGIN

        # Step 6: Apply bounds
        final_timeout = max(cls.MIN_TIMEOUT, min(recommended, cls.MAX_TIMEOUT))

        logger.info(
            "Predicted timeout for %s: %.1fs (p95=%.1fs, adjusted=%.1fs, final=%.1fs)",
            operation, final_timeout, p95_duration, adjusted, final_timeout
        )

        return final_timeout

    @classmethod
    def predict_timeout_simple(cls, operation: str) -> float:
        """
        Simplified prediction without contextual adjustment.

        Useful for quick estimates when context is not available.

        Args:
            operation: Operation type

        Returns:
            Predicted timeout in seconds
        """
        return cls.predict_timeout(operation, context=None)

    @classmethod
    def get_confidence_level(cls, operation: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Retorna nivel de confianza de la predicción basándose en cantidad de datos históricos.

        Returns:
            "high" (>50 samples), "medium" (10-50), "low" (<10)
        """
        try:
            from .duration_telemetry_service import DurationTelemetryService

            gics = cls._get_gics()
            if gics:
                DurationTelemetryService.set_gics(gics)

            durations = DurationTelemetryService.get_historical_durations(
                operation=operation,
                context=context,
                limit=100,
            )

            sample_count = len(durations)
            if sample_count >= 50:
                return "high"
            elif sample_count >= 10:
                return "medium"
            else:
                return "low"

        except Exception as exc:
            logger.warning("Failed to calculate confidence level: %s", exc)
            return "low"

    @classmethod
    def recommend_timeout_with_metadata(
        cls,
        operation: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Retorna predicción de timeout con metadata adicional.

        Returns:
            {
                "timeout_s": float,
                "confidence": str,
                "sample_count": int,
                "operation": str,
                "based_on_history": bool,
            }
        """
        timeout = cls.predict_timeout(operation, context)
        confidence = cls.get_confidence_level(operation, context)

        # Get sample count for metadata
        sample_count = 0
        try:
            from .duration_telemetry_service import DurationTelemetryService

            gics = cls._get_gics()
            if gics:
                DurationTelemetryService.set_gics(gics)

            durations = DurationTelemetryService.get_historical_durations(
                operation=operation,
                context=context,
                limit=100,
            )
            sample_count = len(durations)
        except Exception:
            pass

        return {
            "timeout_s": round(timeout, 1),
            "confidence": confidence,
            "sample_count": sample_count,
            "operation": operation,
            "based_on_history": sample_count >= 5,
            "default_fallback": sample_count < 5,
        }
