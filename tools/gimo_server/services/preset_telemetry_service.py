"""PresetTelemetryService — Captures preset routing decisions and execution outcomes.

F8.1: Registra qué presets se usan en qué contextos y cómo funcionan, para alimentar
el advisory system de ProfileRouterService.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.services.preset_telemetry")


class PresetTelemetryService:
    """Captures and retrieves preset telemetry for adaptive routing.

    Data model in GICS:
        ops:preset_telemetry:{task_semantic}:{preset_name}
        {
            "task_semantic": str,
            "preset_name": str,
            "samples": int,
            "successes": int,
            "failures": int,
            "success_rate": float,
            "avg_quality_score": float,
            "avg_latency_ms": float,
            "avg_cost_usd": float,
            "quality_samples": int,
            "selected_count": int,
            "execution_count": int,
            "metadata": {
                "last_success_at": timestamp,
                "last_failure_at": timestamp,
                "failure_streak": int,
                "quality_confidence": float,
            },
            "updated_at": timestamp
        }
    """

    # FIX BUG #1: Thread-safe locking to prevent race conditions
    _locks: Dict[str, threading.Lock] = {}
    _locks_lock = threading.Lock()

    @classmethod
    def _get_lock(cls, key: str) -> threading.Lock:
        """Gets or creates a lock for a specific telemetry key."""
        with cls._locks_lock:
            if key not in cls._locks:
                cls._locks[key] = threading.Lock()
            return cls._locks[key]

    @classmethod
    def record_decision(
        cls,
        task_semantic: str,
        preset_name: str,
        alternatives_count: int,
    ) -> None:
        """Registra que un preset fue SELECCIONADO por routing."""
        from ..services.ops_service import OpsService

        gics = getattr(OpsService, '_gics', None)
        if not gics:
            return

        key = f"ops:preset_telemetry:{task_semantic}:{preset_name}"

        # FIX BUG #1: Use lock to prevent race conditions
        with cls._get_lock(key):
            current = cls._get_or_init(key, task_semantic, preset_name, gics)

            # Incrementa selected_count
            current["selected_count"] += 1
            current["updated_at"] = time.time()

            # Persist atómicamente
            gics.put(key, current)

        logger.debug(
            "Recorded decision: semantic=%s, preset=%s, alternatives=%d",
            task_semantic,
            preset_name,
            alternatives_count,
        )

    @classmethod
    def record_outcome(
        cls,
        task_semantic: str,
        preset_name: str,
        success: bool,
        quality_score: Optional[float] = None,
        latency_ms: Optional[float] = None,
        cost_usd: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Registra el RESULTADO de una ejecución con preset.

        Returns:
            Updated telemetry record
        """
        from ..services.ops_service import OpsService

        gics = getattr(OpsService, '_gics', None)
        if not gics:
            return {}

        key = f"ops:preset_telemetry:{task_semantic}:{preset_name}"

        # FIX BUG #1: Use lock to prevent race conditions
        with cls._get_lock(key):
            # Read-modify-write atómico
            current = cls._get_or_init(key, task_semantic, preset_name, gics)

            # FIX BUG #2 & #3: Guardar old_samples ANTES de incrementar
            old_samples = current["samples"]

            # Actualizar counters
            current["samples"] += 1
            current["execution_count"] += 1
            if success:
                current["successes"] += 1
                current["metadata"]["last_success_at"] = time.time()
                current["metadata"]["failure_streak"] = 0
            else:
                current["failures"] += 1
                current["metadata"]["last_failure_at"] = time.time()
                current["metadata"]["failure_streak"] += 1

            # Actualizar promedios (running average) - CORREGIDO
            if quality_score is not None:
                n = current["quality_samples"]
                if n == 0:
                    current["avg_quality_score"] = quality_score
                else:
                    current["avg_quality_score"] = (
                        (current["avg_quality_score"] * n + quality_score) / (n + 1)
                    )
                current["quality_samples"] += 1

            if latency_ms is not None:
                if old_samples == 0:  # FIX: usar old_samples
                    current["avg_latency_ms"] = latency_ms
                else:
                    current["avg_latency_ms"] = (
                        (current["avg_latency_ms"] * old_samples + latency_ms) / current["samples"]
                    )

            if cost_usd is not None:
                if old_samples == 0:  # FIX: usar old_samples
                    current["avg_cost_usd"] = cost_usd
                else:
                    current["avg_cost_usd"] = (
                        (current["avg_cost_usd"] * old_samples + cost_usd) / current["samples"]
                    )

            # Recalcular rates
            current["success_rate"] = current["successes"] / current["samples"] if current["samples"] > 0 else 0.0

            # Calcular confidence interval (Wilson score interval)
            current["metadata"]["quality_confidence"] = cls._calculate_confidence_width(
                current["quality_samples"], current["avg_quality_score"]
            )

            current["updated_at"] = time.time()

            # Persist atómicamente
            gics.put(key, current)

            logger.info(
                "Recorded outcome: semantic=%s, preset=%s, success=%s, quality=%.2f, samples=%d",
                task_semantic,
                preset_name,
                success,
                quality_score or 0.0,
                current["samples"],
            )

            return current

    @classmethod
    def get_telemetry(
        cls,
        task_semantic: str,
        preset_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Obtiene telemetría de un preset para un semantic."""
        from ..services.ops_service import OpsService

        # GICS is injected via OpsService.set_gics()
        gics = getattr(OpsService, '_gics', None)
        if not gics:
            return None

        key = f"ops:preset_telemetry:{task_semantic}:{preset_name}"
        return gics.get(key)

    @classmethod
    def get_all_for_semantic(
        cls,
        task_semantic: str,
    ) -> List[Dict[str, Any]]:
        """Obtiene telemetría de TODOS los presets para un semantic."""
        from ..services.ops_service import OpsService

        gics = getattr(OpsService, '_gics', None)
        if not gics:
            return []

        prefix = f"ops:preset_telemetry:{task_semantic}:"
        return gics.scan(prefix)

    @classmethod
    def _get_or_init(
        cls,
        key: str,
        task_semantic: str,
        preset_name: str,
        gics,
    ) -> Dict[str, Any]:
        """Gets existing telemetry or initializes new record."""
        current = gics.get(key)
        if current:
            return current

        # Initialize new record
        return {
            "task_semantic": task_semantic,
            "preset_name": preset_name,
            "samples": 0,
            "successes": 0,
            "failures": 0,
            "success_rate": 0.0,
            "avg_quality_score": 0.0,
            "avg_latency_ms": 0.0,
            "avg_cost_usd": 0.0,
            "quality_samples": 0,
            "selected_count": 0,
            "execution_count": 0,
            "metadata": {
                "last_success_at": 0.0,
                "last_failure_at": 0.0,
                "failure_streak": 0,
                "quality_confidence": 1.0,  # Máxima incertidumbre inicial
            },
            "updated_at": time.time(),
        }

    @classmethod
    def _calculate_confidence_width(cls, n: int, score: float) -> float:
        """Calcula ancho del intervalo de confianza (Wilson score).

        Returns:
            Width in [0, 1], where 1 = maximum uncertainty, 0 = perfect confidence
        """
        if n < 2:
            return 1.0  # Máxima incertidumbre

        # Simplified Wilson score interval: z=1.96 (95% confidence)
        z = 1.96
        p = score / 100.0  # Normalize to [0, 1]
        p = max(0.01, min(0.99, p))  # Clamp to avoid edge cases

        denominator = 1 + (z**2 / n)
        width = (z / denominator) * math.sqrt((p * (1 - p) / n) + (z**2 / (4 * n**2)))

        return min(1.0, width * 2)  # Full interval width, normalized

    @classmethod
    def seed_initial_priors(cls) -> None:
        """Seedea telemetría inicial desde priors semánticos hardcodeados.

        Usado en startup para evitar cold start. Crea entries sintéticas con N=5 samples
        basadas en los priors semánticos de ProfileRouterService.
        """
        from ..services.ops_service import OpsService
        from ..services.profile_router_service import ProfileRouterService

        gics = getattr(OpsService, '_gics', None)
        if not gics:
            return

        seeded_count = 0

        for task_semantic, presets in ProfileRouterService._SEMANTIC_PRIORS.items():
            for preset_name, prior_score in presets.items():
                key = f"ops:preset_telemetry:{task_semantic}:{preset_name}"

                # Solo seed si no existe
                if gics.get(key):
                    continue

                # Crear telemetría sintética con N=5 samples
                # prior_score está en [0, 0.45], normalizar a success_rate [0, 1]
                synthetic_success_rate = min(1.0, prior_score / 0.45)
                synthetic_quality = min(100.0, (prior_score / 0.45) * 100)
                synthetic_successes = int(5 * synthetic_success_rate)
                synthetic_failures = 5 - synthetic_successes

                gics.put(key, {
                    "task_semantic": task_semantic,
                    "preset_name": preset_name,
                    "samples": 5,
                    "successes": synthetic_successes,
                    "failures": synthetic_failures,
                    "success_rate": synthetic_success_rate,
                    "avg_quality_score": synthetic_quality,
                    "quality_samples": 5,
                    "avg_latency_ms": 0.0,
                    "avg_cost_usd": 0.0,
                    "selected_count": 0,
                    "execution_count": 0,
                    "metadata": {
                        "seeded": True,
                        "last_success_at": time.time(),
                        "last_failure_at": 0.0,
                        "failure_streak": 0,
                        "quality_confidence": 0.8,  # Moderada confianza en seeds
                    },
                    "updated_at": time.time(),
                })
                seeded_count += 1

        logger.info("Seeded %d preset telemetry entries from priors", seeded_count)
