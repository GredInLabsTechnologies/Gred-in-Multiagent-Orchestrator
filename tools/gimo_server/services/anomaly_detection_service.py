"""AnomalyDetectionService — Statistical anomaly detection for preset performance.

P9: Detecta degradación de presets mediante baselines estadísticos (μ, σ) y
auto-downgrade de presets con failure_streak persistente.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.services.anomaly_detection")


class AnomalyDetectionService:
    """Detects statistical anomalies in preset telemetry and manages auto-downgrade.

    Estrategia:
    - Compute baseline (μ, σ) desde histórico de quality_score
    - Detect anomaly: current_quality < μ - 2σ (95.4% confidence)
    - Auto-downgrade: failure_streak ≥ 5 → exclude from routing
    """

    # Thresholds
    BASELINE_MIN_SAMPLES = 20  # Mínimo samples para baseline confiable
    ANOMALY_THRESHOLD_SIGMA = 2.0  # 2σ para detectar anomalías
    DOWNGRADE_FAILURE_STREAK = 5  # Streak para auto-downgrade
    ANOMALY_SEVERITY_THRESHOLD = 10.0  # Gap adicional para severity="high"

    @classmethod
    def compute_baseline(
        cls,
        task_semantic: str,
        preset_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Calcula baseline estadístico (μ, σ) para un preset.

        Args:
            task_semantic: Contexto semántico ("planning", "research", etc)
            preset_name: Nombre del preset ("plan_orchestrator", "researcher", etc)

        Returns:
            {
                "mean": float,           # μ de quality_score
                "stdev": float,          # σ de quality_score
                "samples": int,          # N usado para calcular
                "confidence": str,       # "low" | "medium" | "high"
                "min_quality": float,    # Min observado
                "max_quality": float,    # Max observado
            }
            None si no hay suficientes datos
        """
        from .preset_telemetry_service import PresetTelemetryService

        telemetry = PresetTelemetryService.get_telemetry(task_semantic, preset_name)

        if not telemetry:
            return None

        samples = telemetry.get("quality_samples", 0)
        if samples < 2:
            return None

        # Para baseline confiable, necesitamos histórico
        # Como PresetTelemetryService solo guarda running average,
        # usamos avg_quality_score y estimamos stdev desde success_rate variance
        avg_quality = telemetry["avg_quality_score"]
        success_rate = telemetry["success_rate"]

        # Heurística: stdev estimado desde success_rate
        # High success_rate → low variance, low success_rate → high variance
        # Typical: σ ≈ 15 * (1 - success_rate) para quality scores
        estimated_stdev = 15.0 * (1.0 - success_rate) + 5.0  # Min σ=5, max σ=20

        # Confidence basado en samples
        if samples < cls.BASELINE_MIN_SAMPLES:
            confidence = "low"
        elif samples < 50:
            confidence = "medium"
        else:
            confidence = "high"

        # Min/Max estimados desde mean±stdev
        min_quality = max(0.0, avg_quality - 2 * estimated_stdev)
        max_quality = min(100.0, avg_quality + 2 * estimated_stdev)

        baseline = {
            "task_semantic": task_semantic,
            "preset_name": preset_name,
            "mean": avg_quality,
            "stdev": estimated_stdev,
            "samples": samples,
            "confidence": confidence,
            "min_quality": min_quality,
            "max_quality": max_quality,
        }

        logger.debug(
            "Computed baseline: semantic=%s, preset=%s, mean=%.2f, stdev=%.2f, samples=%d, conf=%s",
            task_semantic,
            preset_name,
            avg_quality,
            estimated_stdev,
            samples,
            confidence,
        )

        return baseline

    @classmethod
    def detect_anomalies(cls) -> List[Dict[str, Any]]:
        """Escanea todos los presets y detecta anomalías estadísticas.

        Returns:
            Lista de anomalías detectadas:
            [
                {
                    "preset": str,
                    "task_semantic": str,
                    "current_quality": float,
                    "baseline_mean": float,
                    "baseline_stdev": float,
                    "threshold": float,        # μ - 2σ
                    "gap": float,              # threshold - current
                    "severity": str,           # "medium" | "high"
                    "samples": int,
                    "confidence": str,
                },
                ...
            ]
        """
        from .gics_service import GicsService

        anomalies: List[Dict[str, Any]] = []

        # Scan all telemetry entries
        prefix = "ops:preset_telemetry:"
        all_telemetry = GicsService.scan(prefix)

        for telemetry in all_telemetry:
            task_semantic = telemetry.get("task_semantic")
            preset_name = telemetry.get("preset_name")

            if not task_semantic or not preset_name:
                continue

            # Compute baseline
            baseline = cls.compute_baseline(task_semantic, preset_name)
            if not baseline or baseline["confidence"] == "low":
                continue  # No baseline confiable

            # Check anomaly
            current_quality = telemetry["avg_quality_score"]
            threshold = baseline["mean"] - (cls.ANOMALY_THRESHOLD_SIGMA * baseline["stdev"])
            gap = threshold - current_quality

            if current_quality < threshold:
                # ANOMALY DETECTED
                severity = "high" if gap > cls.ANOMALY_SEVERITY_THRESHOLD else "medium"

                anomaly = {
                    "preset": preset_name,
                    "task_semantic": task_semantic,
                    "current_quality": current_quality,
                    "baseline_mean": baseline["mean"],
                    "baseline_stdev": baseline["stdev"],
                    "threshold": threshold,
                    "gap": gap,
                    "severity": severity,
                    "samples": baseline["samples"],
                    "confidence": baseline["confidence"],
                }

                anomalies.append(anomaly)

                logger.warning(
                    "ANOMALY DETECTED: preset=%s, semantic=%s, current=%.1f, baseline=%.1f±%.1f, threshold=%.1f, gap=%.1f, severity=%s",
                    preset_name,
                    task_semantic,
                    current_quality,
                    baseline["mean"],
                    baseline["stdev"],
                    threshold,
                    gap,
                    severity,
                )

        return anomalies

    @classmethod
    def get_downgrade_list(cls) -> List[str]:
        """Obtiene lista de presets que deben ser auto-downgraded.

        Returns:
            Lista de preset_names con failure_streak ≥ 5
        """
        from .gics_service import GicsService

        downgraded: List[str] = []

        # Scan all telemetry
        prefix = "ops:preset_telemetry:"
        all_telemetry = GicsService.scan(prefix)

        for telemetry in all_telemetry:
            preset_name = telemetry.get("preset_name")
            failure_streak = telemetry.get("metadata", {}).get("failure_streak", 0)

            if failure_streak >= cls.DOWNGRADE_FAILURE_STREAK:
                downgraded.append(preset_name)
                logger.info(
                    "Preset downgraded: %s (failure_streak=%d)",
                    preset_name,
                    failure_streak,
                )

        return downgraded

    @classmethod
    async def notify_critical_anomalies(cls, anomalies: List[Dict[str, Any]]) -> None:
        """Notifica anomalías críticas via NotificationService.

        Args:
            anomalies: Lista de anomalías detectadas
        """
        from .notification_service import NotificationService

        for anomaly in anomalies:
            if anomaly["severity"] == "high":
                await NotificationService.publish(
                    "preset_anomaly_detected",
                    {
                        "critical": True,
                        "preset": anomaly["preset"],
                        "task_semantic": anomaly["task_semantic"],
                        "current_quality": anomaly["current_quality"],
                        "baseline_mean": anomaly["baseline_mean"],
                        "threshold": anomaly["threshold"],
                        "gap": anomaly["gap"],
                    },
                )

                logger.critical(
                    "CRITICAL ANOMALY NOTIFIED: preset=%s, semantic=%s, gap=%.1f",
                    anomaly["preset"],
                    anomaly["task_semantic"],
                    anomaly["gap"],
                )
