"""Three-phase thermal protection — NON-BYPASSABLE safety valve.

Phase 1 (warn):    Log warning, continue execution
Phase 2 (throttle): Reduce workload, notify core
Phase 3 (lockout):  Unload model, abort task, block device until safe
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .config import AgentConfig

logger = logging.getLogger("gimo_mesh_agent.thermal")


class ThermalPhase(str, Enum):
    normal = "normal"
    warning = "warning"
    throttle = "throttle"
    lockout = "lockout"


# Severity ordering for monotonic escalation
_PHASE_SEVERITY = {
    ThermalPhase.normal: 0,
    ThermalPhase.warning: 1,
    ThermalPhase.throttle: 2,
    ThermalPhase.lockout: 3,
}


@dataclass
class ThermalSnapshot:
    cpu_temp_c: float = -1.0
    gpu_temp_c: float = -1.0
    battery_temp_c: float = -1.0
    phase: ThermalPhase = ThermalPhase.normal
    trigger_sensor: str = ""
    trigger_value: float = 0.0
    trigger_threshold: float = 0.0


class ThermalGuard:
    """Non-bypassable three-phase thermal protection.

    Operator CANNOT override lockout. Only safe conditions or user action
    on the physical device can clear it.
    """

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._phase = ThermalPhase.normal
        self._lockout_since: Optional[datetime] = None

    @property
    def phase(self) -> ThermalPhase:
        return self._phase

    @property
    def is_locked_out(self) -> bool:
        return self._phase == ThermalPhase.lockout

    def evaluate(
        self,
        cpu_temp_c: float = -1.0,
        gpu_temp_c: float = -1.0,
        battery_temp_c: float = -1.0,
    ) -> ThermalSnapshot:
        """Evaluate temperatures and return current thermal state.

        Transitions are monotonic upward within a single evaluation:
        normal → warning → throttle → lockout.
        Downward transitions require explicit clear_if_safe().
        """
        snapshot = ThermalSnapshot(
            cpu_temp_c=cpu_temp_c,
            gpu_temp_c=gpu_temp_c,
            battery_temp_c=battery_temp_c,
            phase=ThermalPhase.normal,
        )

        # Check lockout thresholds first (highest priority)
        if cpu_temp_c >= self._config.thermal_lockout_cpu > 0:
            snapshot.phase = ThermalPhase.lockout
            snapshot.trigger_sensor = "cpu"
            snapshot.trigger_value = cpu_temp_c
            snapshot.trigger_threshold = self._config.thermal_lockout_cpu
        elif gpu_temp_c >= self._config.thermal_lockout_gpu > 0:
            snapshot.phase = ThermalPhase.lockout
            snapshot.trigger_sensor = "gpu"
            snapshot.trigger_value = gpu_temp_c
            snapshot.trigger_threshold = self._config.thermal_lockout_gpu
        elif battery_temp_c >= self._config.thermal_lockout_battery > 0:
            snapshot.phase = ThermalPhase.lockout
            snapshot.trigger_sensor = "battery"
            snapshot.trigger_value = battery_temp_c
            snapshot.trigger_threshold = self._config.thermal_lockout_battery
        # Throttle thresholds
        elif cpu_temp_c >= self._config.thermal_throttle_cpu > 0:
            snapshot.phase = ThermalPhase.throttle
            snapshot.trigger_sensor = "cpu"
            snapshot.trigger_value = cpu_temp_c
            snapshot.trigger_threshold = self._config.thermal_throttle_cpu
        elif gpu_temp_c >= self._config.thermal_throttle_gpu > 0:
            snapshot.phase = ThermalPhase.throttle
            snapshot.trigger_sensor = "gpu"
            snapshot.trigger_value = gpu_temp_c
            snapshot.trigger_threshold = self._config.thermal_throttle_gpu
        elif battery_temp_c >= self._config.thermal_throttle_battery > 0:
            snapshot.phase = ThermalPhase.throttle
            snapshot.trigger_sensor = "battery"
            snapshot.trigger_value = battery_temp_c
            snapshot.trigger_threshold = self._config.thermal_throttle_battery
        # Warning thresholds
        elif cpu_temp_c >= self._config.thermal_warn_cpu > 0:
            snapshot.phase = ThermalPhase.warning
            snapshot.trigger_sensor = "cpu"
            snapshot.trigger_value = cpu_temp_c
            snapshot.trigger_threshold = self._config.thermal_warn_cpu
        elif gpu_temp_c >= self._config.thermal_warn_gpu > 0:
            snapshot.phase = ThermalPhase.warning
            snapshot.trigger_sensor = "gpu"
            snapshot.trigger_value = gpu_temp_c
            snapshot.trigger_threshold = self._config.thermal_warn_gpu
        elif battery_temp_c >= self._config.thermal_warn_battery > 0:
            snapshot.phase = ThermalPhase.warning
            snapshot.trigger_sensor = "battery"
            snapshot.trigger_value = battery_temp_c
            snapshot.trigger_threshold = self._config.thermal_warn_battery

        # Phase can only go UP, never down (monotonic within evaluation)
        if self._phase == ThermalPhase.lockout:
            snapshot.phase = ThermalPhase.lockout
        elif _PHASE_SEVERITY[snapshot.phase] > _PHASE_SEVERITY[self._phase]:
            pass  # Allow escalation
        else:
            snapshot.phase = self._phase

        # Apply phase
        old_phase = self._phase
        self._phase = snapshot.phase

        if snapshot.phase == ThermalPhase.lockout and old_phase != ThermalPhase.lockout:
            self._lockout_since = datetime.now(timezone.utc)
            logger.critical(
                "THERMAL LOCKOUT: %s=%.1f°C (threshold=%.1f°C) — model will be unloaded",
                snapshot.trigger_sensor, snapshot.trigger_value, snapshot.trigger_threshold,
            )
        elif snapshot.phase == ThermalPhase.throttle and old_phase != ThermalPhase.throttle:
            logger.warning(
                "THERMAL THROTTLE: %s=%.1f°C (threshold=%.1f°C)",
                snapshot.trigger_sensor, snapshot.trigger_value, snapshot.trigger_threshold,
            )
        elif snapshot.phase == ThermalPhase.warning and old_phase == ThermalPhase.normal:
            logger.warning(
                "THERMAL WARNING: %s=%.1f°C (threshold=%.1f°C)",
                snapshot.trigger_sensor, snapshot.trigger_value, snapshot.trigger_threshold,
            )

        return snapshot

    def clear_if_safe(
        self,
        cpu_temp_c: float = -1.0,
        gpu_temp_c: float = -1.0,
        battery_temp_c: float = -1.0,
    ) -> bool:
        """Attempt to clear lockout. Only succeeds if ALL temps are below warning thresholds.

        This is the ONLY way to exit lockout — it cannot be bypassed by operator command.
        """
        if not self.is_locked_out:
            return True

        # All must be below warning thresholds to clear
        cpu_safe = cpu_temp_c < 0 or cpu_temp_c < self._config.thermal_warn_cpu
        gpu_safe = gpu_temp_c < 0 or gpu_temp_c < self._config.thermal_warn_gpu
        bat_safe = battery_temp_c < 0 or battery_temp_c < self._config.thermal_warn_battery

        if cpu_safe and gpu_safe and bat_safe:
            logger.info("Thermal lockout cleared — all sensors below warning thresholds")
            self._phase = ThermalPhase.normal
            self._lockout_since = None
            return True

        return False
