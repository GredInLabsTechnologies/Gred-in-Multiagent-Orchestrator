"""Telemetry ingestion + aggregation + thermal profiles.

Ingests thermal events from device agents, builds per-device thermal profiles,
computes device health scores, and feeds GICS for routing optimization.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from filelock import FileLock

from ...config import OPS_DATA_DIR
from ...models.mesh import ThermalEvent

logger = logging.getLogger("orchestrator.mesh.telemetry")

_MESH_DIR = OPS_DATA_DIR / "mesh"
_PROFILES_DIR = _MESH_DIR / "thermal_profiles"
_LOCK_FILE = _MESH_DIR / ".telemetry.lock"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeviceThermalProfile:
    """Tracks thermal behavior of a device over time."""

    def __init__(self, device_id: str, data: Optional[Dict[str, Any]] = None) -> None:
        self.device_id = device_id
        d = data or {}
        self.total_events: int = int(d.get("total_events", 0))
        self.warnings: int = int(d.get("warnings", 0))
        self.throttles: int = int(d.get("throttles", 0))
        self.lockouts: int = int(d.get("lockouts", 0))
        self.avg_time_to_throttle_min: float = float(d.get("avg_time_to_throttle_min", 0.0))
        self.avg_time_to_lockout_min: float = float(d.get("avg_time_to_lockout_min", 0.0))
        self.worst_cpu_temp: float = float(d.get("worst_cpu_temp", 0.0))
        self.worst_gpu_temp: float = float(d.get("worst_gpu_temp", 0.0))
        self.worst_battery_temp: float = float(d.get("worst_battery_temp", 0.0))
        self.last_event_at: str = d.get("last_event_at", "")
        self.recommended_duty_cycle_min: float = float(d.get("recommended_duty_cycle_min", 0.0))
        self.health_score: float = float(d.get("health_score", 100.0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "total_events": self.total_events,
            "warnings": self.warnings,
            "throttles": self.throttles,
            "lockouts": self.lockouts,
            "avg_time_to_throttle_min": round(self.avg_time_to_throttle_min, 1),
            "avg_time_to_lockout_min": round(self.avg_time_to_lockout_min, 1),
            "worst_cpu_temp": round(self.worst_cpu_temp, 1),
            "worst_gpu_temp": round(self.worst_gpu_temp, 1),
            "worst_battery_temp": round(self.worst_battery_temp, 1),
            "last_event_at": self.last_event_at,
            "recommended_duty_cycle_min": round(self.recommended_duty_cycle_min, 1),
            "health_score": round(self.health_score, 1),
        }


_singleton_instance: Optional["TelemetryService"] = None


class TelemetryService:
    """Ingests thermal events, builds profiles, computes health scores.

    Use get_instance() to access the singleton.
    """

    def __new__(cls) -> "TelemetryService":
        global _singleton_instance
        if _singleton_instance is None:
            _singleton_instance = super().__new__(cls)
            _singleton_instance._initialized = False
        return _singleton_instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    def _lock(self) -> FileLock:
        return FileLock(str(_LOCK_FILE), timeout=5)

    # ── Ingestion ────────────────────────────────────────────

    def ingest_thermal_event(self, event: ThermalEvent) -> DeviceThermalProfile:
        """Process a thermal event and update the device's thermal profile."""
        profile = self.get_profile(event.device_id)

        profile.total_events += 1
        profile.last_event_at = event.timestamp.isoformat()

        if event.event_type == "warning":
            profile.warnings += 1
        elif event.event_type == "throttle":
            profile.throttles += 1
            # Update average time to throttle
            if event.duration_before_trigger_minutes > 0:
                n = profile.throttles
                prev = profile.avg_time_to_throttle_min
                profile.avg_time_to_throttle_min = (
                    (prev * (n - 1) + event.duration_before_trigger_minutes) / n
                )
        elif event.event_type == "lockout":
            profile.lockouts += 1
            if event.duration_before_trigger_minutes > 0:
                n = profile.lockouts
                prev = profile.avg_time_to_lockout_min
                profile.avg_time_to_lockout_min = (
                    (prev * (n - 1) + event.duration_before_trigger_minutes) / n
                )

        # Track worst temps
        if event.trigger_sensor == "cpu":
            profile.worst_cpu_temp = max(profile.worst_cpu_temp, event.trigger_value)
        elif event.trigger_sensor == "gpu":
            profile.worst_gpu_temp = max(profile.worst_gpu_temp, event.trigger_value)
        elif event.trigger_sensor == "battery":
            profile.worst_battery_temp = max(profile.worst_battery_temp, event.trigger_value)

        # Recompute health score and duty cycle
        profile.health_score = self._compute_health_score(profile)
        profile.recommended_duty_cycle_min = self._compute_duty_cycle(profile)

        self._save_profile(profile)
        return profile

    # ── Health score ─────────────────────────────────────────

    @staticmethod
    def _compute_health_score(profile: DeviceThermalProfile) -> float:
        """Device health score: 100 = pristine, 0 = severely degraded.

        Penalties with temporal decay — recent events weigh more.
        Events older than 7 days are discounted by 50%.
        Raw penalties: lockout=-5, throttle=-2, warning=-0.5.
        """
        score = 100.0
        # Temporal decay factor: reduce penalty for old profiles
        decay = 1.0
        if profile.last_event_at:
            try:
                last = datetime.fromisoformat(profile.last_event_at)
                age_days = (_utcnow() - last).total_seconds() / 86400
                if age_days > 7:
                    decay = 0.5  # Old events matter less
                elif age_days > 3:
                    decay = 0.75
            except (ValueError, TypeError):
                pass
        score -= profile.lockouts * 5.0 * decay
        score -= profile.throttles * 2.0 * decay
        score -= profile.warnings * 0.5 * decay
        return max(0.0, score)

    # ── Duty cycle scheduling ────────────────────────────────

    @staticmethod
    def _compute_duty_cycle(profile: DeviceThermalProfile) -> float:
        """Recommended max continuous duty in minutes based on thermal history.

        If the device has never throttled, no limit (0 = unlimited).
        Otherwise, recommend 80% of average time to first throttle.
        """
        if profile.throttles == 0:
            return 0.0  # No limit
        if profile.avg_time_to_throttle_min > 0:
            return profile.avg_time_to_throttle_min * 0.8
        return 15.0  # Conservative default if data is sparse

    # ── Profile CRUD ─────────────────────────────────────────

    def get_profile(self, device_id: str) -> DeviceThermalProfile:
        path = _PROFILES_DIR / f"{device_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return DeviceThermalProfile(device_id, data)
            except Exception:
                logger.warning("Failed to load profile for %s", device_id)
        return DeviceThermalProfile(device_id)

    def list_profiles(self) -> List[DeviceThermalProfile]:
        profiles: List[DeviceThermalProfile] = []
        for p in sorted(_PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                did = p.stem
                profiles.append(DeviceThermalProfile(did, data))
            except Exception:
                continue
        return profiles

    def _save_profile(self, profile: DeviceThermalProfile) -> None:
        with self._lock():
            path = _PROFILES_DIR / f"{profile.device_id}.json"
            path.write_text(
                json.dumps(profile.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )

    # ── GICS integration ─────────────────────────────────────

    def feed_gics(
        self,
        gics,
        event: ThermalEvent,
        profile: DeviceThermalProfile,
    ) -> None:
        """Feed thermal data to GICS for routing optimization.

        Records thermal events as negative signals for the model+task combo
        that triggered overheating.
        """
        if not gics or not event.task_fingerprint:
            return

        try:
            gics._record_task_pattern(
                provider_type="mesh_device",
                model_id=event.model_loaded or "unknown",
                task_type=event.task_fingerprint,
                success=False,  # Thermal event = negative signal
                latency_ms=event.duration_before_trigger_minutes * 60000,
            )
            logger.info(
                "Fed GICS thermal signal: device=%s model=%s task=%s health=%.0f",
                event.device_id, event.model_loaded, event.task_fingerprint, profile.health_score,
            )
        except Exception as exc:
            logger.warning("Failed to feed GICS: %s", exc)
