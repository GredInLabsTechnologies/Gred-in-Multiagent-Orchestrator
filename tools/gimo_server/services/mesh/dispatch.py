"""Intelligent dispatch — routes sub-tasks to mesh devices.

Combines GICS patterns, device capacity, thermal state, health score,
and thermal-predictive pre-checks for optimal device selection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...models.mesh import MeshDeviceInfo, TaskFingerprint
from ..gics_service import GicsService
from .pattern_matcher import PatternMatcher
from .registry import MeshRegistry
from .telemetry import TelemetryService

logger = logging.getLogger("orchestrator.mesh.dispatch")


@dataclass
class DispatchDecision:
    """Result of dispatch routing."""
    device_id: str = ""
    model_id: str = ""
    reason: str = ""
    fallback_to_local: bool = False
    thermal_headroom_ok: bool = True
    health_score: float = 100.0
    duty_cycle_remaining_min: float = 0.0
    inference_endpoint: str = ""


class DispatchService:
    """Routes sub-tasks to optimal mesh devices."""

    def __init__(
        self,
        registry: MeshRegistry,
        gics: Optional[GicsService] = None,
    ) -> None:
        self._registry = registry
        self._gics = gics
        self._matcher = PatternMatcher(gics) if gics else None
        self._telemetry = TelemetryService()

    def dispatch(
        self,
        fingerprint: TaskFingerprint,
        mesh_enabled: bool,
        preferred_model: str = "",
    ) -> DispatchDecision:
        """Select the best device for a task.

        Pipeline:
        1. Get eligible devices
        2. Filter by capacity (model params)
        3. Thermal-predictive pre-check
        4. Score by health + GICS pattern match
        5. Select best device + model via Thompson Sampling
        6. Fallback to local if no eligible device
        """
        if not mesh_enabled:
            return DispatchDecision(
                fallback_to_local=True,
                reason="Mesh disabled",
            )

        eligible = self._registry.get_eligible_devices(mesh_enabled)
        if not eligible:
            return DispatchDecision(
                fallback_to_local=True,
                reason="No eligible mesh devices",
            )

        # Filter by capacity if fingerprint specifies context requirements
        if fingerprint.requires_context_kb > 0:
            eligible = [
                d for d in eligible
                if d.max_model_params_b > 0  # Has capacity info
            ]

        if not eligible:
            return DispatchDecision(
                fallback_to_local=True,
                reason="No devices with sufficient capacity",
            )

        # Staleness filter: reject devices with no recent heartbeat
        eligible = self._filter_stale_heartbeats(eligible)
        if not eligible:
            return DispatchDecision(
                fallback_to_local=True,
                reason="All eligible devices have stale heartbeats",
            )

        # Thermal-predictive pre-check: filter out devices that are close to throttle
        eligible = self._filter_thermal_headroom(eligible)
        if not eligible:
            return DispatchDecision(
                fallback_to_local=True,
                reason="All eligible devices near thermal limit",
                thermal_headroom_ok=False,
            )

        # Score devices by health + thermal profile
        scored = self._score_devices(eligible)

        # Select best device
        best = scored[0]
        device = best["device"]

        # Model selection via Thompson Sampling
        model_id = preferred_model
        if not model_id and self._matcher and device.model_loaded:
            available_models = self._get_available_models(eligible)
            if available_models:
                model_id = self._matcher.select_model(fingerprint, available_models)

        if not model_id and device.model_loaded:
            model_id = device.model_loaded

        return DispatchDecision(
            device_id=device.device_id,
            model_id=model_id,
            reason=f"Best score: {best['score']:.2f} (health={best['health']:.0f})",
            thermal_headroom_ok=True,
            health_score=best["health"],
            duty_cycle_remaining_min=best.get("duty_remaining", 0.0),
            inference_endpoint=device.inference_endpoint,
        )

    @staticmethod
    def _filter_stale_heartbeats(
        devices: List[MeshDeviceInfo], max_age_seconds: float = 120.0
    ) -> List[MeshDeviceInfo]:
        """Reject devices whose last heartbeat is too old."""
        now = datetime.now(timezone.utc)
        fresh: List[MeshDeviceInfo] = []
        for d in devices:
            if d.last_heartbeat is None:
                logger.debug("Skipping %s: no heartbeat recorded", d.device_id)
                continue
            age = (now - d.last_heartbeat).total_seconds()
            if age > max_age_seconds:
                logger.debug("Skipping %s: heartbeat stale (%.0fs)", d.device_id, age)
                continue
            fresh.append(d)
        return fresh

    def _filter_thermal_headroom(
        self, devices: List[MeshDeviceInfo]
    ) -> List[MeshDeviceInfo]:
        """Thermal-predictive pre-check: reject devices that are already warm.

        Novel approach — no competitor does this. Check headroom BEFORE dispatch.
        """
        safe: List[MeshDeviceInfo] = []
        for d in devices:
            # Skip if already throttled
            if d.thermal_throttled:
                logger.debug("Skipping %s: already throttled", d.device_id)
                continue

            # Check if temps are above 70% of typical thresholds
            cpu_hot = d.cpu_temp_c > 0 and d.cpu_temp_c > 65.0
            gpu_hot = d.gpu_temp_c > 0 and d.gpu_temp_c > 70.0
            bat_hot = d.battery_temp_c > 0 and d.battery_temp_c > 35.0

            if cpu_hot and gpu_hot:
                logger.debug("Skipping %s: CPU+GPU too warm (%.1f/%.1f)", d.device_id, d.cpu_temp_c, d.gpu_temp_c)
                continue
            if bat_hot and (cpu_hot or gpu_hot):
                logger.debug("Skipping %s: battery+compute too warm", d.device_id)
                continue

            safe.append(d)

        return safe

    def _score_devices(
        self, devices: List[MeshDeviceInfo]
    ) -> List[Dict[str, Any]]:
        """Score devices by health, thermal state, and resource availability."""
        scored: List[Dict[str, Any]] = []

        for d in devices:
            profile = self._telemetry.get_profile(d.device_id)
            health = profile.health_score
            duty_remaining = 0.0

            if profile.recommended_duty_cycle_min > 0:
                # Estimate remaining duty from thermal profile
                duty_remaining = profile.recommended_duty_cycle_min

            # Composite score: health (0-100) + resource availability bonus
            score = health
            # Bonus for low CPU/RAM usage
            if d.cpu_percent < 50:
                score += 10
            if d.ram_percent < 70:
                score += 5
            # Bonus for battery (if on battery, prefer charged devices)
            if d.battery_percent > 50:
                score += 5
            elif d.battery_percent > 0 and d.battery_percent < 20:
                score -= 10  # Penalty for low battery

            scored.append({
                "device": d,
                "score": score,
                "health": health,
                "duty_remaining": duty_remaining,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    @staticmethod
    def _get_available_models(devices: List[MeshDeviceInfo]) -> List[str]:
        """Collect unique loaded models across eligible devices."""
        models: set[str] = set()
        for d in devices:
            if d.model_loaded:
                models.add(d.model_loaded)
        return sorted(models)

    # ── Quantization-aware routing ───────────────────────────

    def suggest_quantization(self, device: MeshDeviceInfo) -> str:
        """Suggest quantization level based on device thermal state.

        Q4 = lower quality, less compute, less heat
        Q8 = higher quality, more compute, more heat
        """
        if device.cpu_temp_c > 70 or device.gpu_temp_c > 75:
            return "Q4_K_M"  # Reduce quality to reduce heat
        if device.battery_temp_c > 38:
            return "Q4_K_M"
        if device.ram_percent > 85:
            return "Q4_K_M"  # Also reduce if RAM pressure
        return "Q8_0"  # Full quality when thermal headroom exists
