from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock

from ...config import OPS_DATA_DIR
from ...models.mesh import (
    ConnectionState,
    DeviceMode,
    HeartbeatPayload,
    MeshDeviceInfo,
    MeshStatus,
    OperationalState,
    ThermalEvent,
)

logger = logging.getLogger("orchestrator.mesh.registry")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


# Valid state transitions for ConnectionState
_CONNECTION_TRANSITIONS: Dict[ConnectionState, set[ConnectionState]] = {
    ConnectionState.offline: {
        ConnectionState.discoverable,
    },
    ConnectionState.discoverable: {
        ConnectionState.pending_approval,
        ConnectionState.offline,
    },
    ConnectionState.pending_approval: {
        ConnectionState.approved,
        ConnectionState.refused,
        ConnectionState.offline,
    },
    ConnectionState.approved: {
        ConnectionState.connected,
        ConnectionState.offline,
    },
    ConnectionState.refused: {
        ConnectionState.pending_approval,
        ConnectionState.offline,
    },
    ConnectionState.connected: {
        ConnectionState.reconnecting,
        ConnectionState.offline,
        ConnectionState.thermal_lockout,
    },
    ConnectionState.reconnecting: {
        ConnectionState.connected,
        ConnectionState.offline,
    },
    ConnectionState.thermal_lockout: {
        ConnectionState.connected,
        ConnectionState.offline,
    },
}


class MeshRegistry:
    """File-backed device registry for GIMO Mesh.

    Storage: .orch_data/ops/mesh/devices/<device_id>.json
    Thermal log: .orch_data/ops/mesh/thermal_events.jsonl
    """

    MESH_DIR = OPS_DATA_DIR / "mesh"
    DEVICES_DIR = MESH_DIR / "devices"
    TOKENS_DIR = MESH_DIR / "tokens"
    THERMAL_LOG = MESH_DIR / "thermal_events.jsonl"
    LOCK_FILE = MESH_DIR / ".mesh.lock"

    def __init__(self) -> None:
        self.MESH_DIR.mkdir(parents=True, exist_ok=True)
        self.DEVICES_DIR.mkdir(parents=True, exist_ok=True)
        self.TOKENS_DIR.mkdir(parents=True, exist_ok=True)

    def _lock(self) -> FileLock:
        return FileLock(str(self.LOCK_FILE), timeout=5)

    # ── Device CRUD ──────────────────────────────────────────

    def _device_path(self, device_id: str) -> Path:
        return self.DEVICES_DIR / f"{device_id}.json"

    def get_device(self, device_id: str) -> Optional[MeshDeviceInfo]:
        path = self._device_path(device_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return MeshDeviceInfo(**data)
        except Exception:
            logger.exception("Failed to load device %s", device_id)
            return None

    def list_devices(self) -> List[MeshDeviceInfo]:
        devices: List[MeshDeviceInfo] = []
        for p in sorted(self.DEVICES_DIR.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                devices.append(MeshDeviceInfo(**data))
            except Exception:
                logger.warning("Skipping corrupt device file %s", p.name)
        return devices

    def save_device(self, device: MeshDeviceInfo) -> None:
        with self._lock():
            path = self._device_path(device.device_id)
            path.write_text(
                _json_dump(device.model_dump(mode="json")),
                encoding="utf-8",
            )

    def remove_device(self, device_id: str) -> bool:
        with self._lock():
            path = self._device_path(device_id)
            if path.exists():
                path.unlink()
                return True
            return False

    # ── Enrollment ───────────────────────────────────────────

    def enroll_device(
        self,
        device_id: str,
        name: str = "",
        device_mode: DeviceMode = DeviceMode.inference,
        device_class: str = "desktop",
    ) -> MeshDeviceInfo:
        now = _utcnow()
        device = MeshDeviceInfo(
            device_id=device_id,
            name=name or device_id,
            device_mode=device_mode,
            connection_state=ConnectionState.pending_approval,
            operational_state=OperationalState.idle,
            device_class=device_class,
            enrolled_at=now,
            last_heartbeat=now,
        )
        self.save_device(device)
        logger.info("Enrolled device %s (mode=%s)", device_id, device_mode)
        return device

    # ── State transitions ────────────────────────────────────

    def set_connection_state(
        self, device_id: str, new_state: ConnectionState
    ) -> MeshDeviceInfo:
        device = self.get_device(device_id)
        if device is None:
            raise ValueError(f"Device {device_id} not found")

        allowed = _CONNECTION_TRANSITIONS.get(device.connection_state, set())
        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {device.connection_state.value} → {new_state.value}"
            )

        old_state = device.connection_state
        device.connection_state = new_state
        self.save_device(device)
        logger.info("Device %s: %s → %s", device_id, old_state.value, new_state.value)
        return device

    def approve_device(self, device_id: str) -> MeshDeviceInfo:
        return self.set_connection_state(device_id, ConnectionState.approved)

    def refuse_device(self, device_id: str) -> MeshDeviceInfo:
        return self.set_connection_state(device_id, ConnectionState.refused)

    # ── Heartbeat processing ─────────────────────────────────

    def process_heartbeat(self, payload: HeartbeatPayload) -> MeshDeviceInfo:
        device = self.get_device(payload.device_id)
        if device is None:
            raise ValueError(f"Device {payload.device_id} not registered")

        device.last_heartbeat = _utcnow()
        device.device_mode = payload.device_mode
        device.operational_state = payload.operational_state
        device.device_class = payload.device_class
        device.soc_model = payload.soc_model
        device.max_model_params_b = payload.max_model_params_b
        device.model_loaded = payload.model_loaded
        device.health_score = payload.health_score
        device.cpu_percent = payload.cpu_percent
        device.ram_percent = payload.ram_percent
        device.cpu_temp_c = payload.cpu_temp_c
        device.gpu_temp_c = payload.gpu_temp_c
        device.battery_percent = payload.battery_percent
        device.battery_charging = payload.battery_charging
        device.battery_temp_c = payload.battery_temp_c
        device.thermal_throttled = payload.thermal_throttled
        device.thermal_locked_out = payload.thermal_locked_out
        device.active_task_id = payload.active_task_id

        # Auto-transition to connected if approved
        if device.connection_state == ConnectionState.approved:
            device.connection_state = ConnectionState.connected
        elif device.connection_state == ConnectionState.reconnecting:
            device.connection_state = ConnectionState.connected

        # Thermal lockout — non-bypassable safety valve
        if payload.thermal_locked_out:
            device.connection_state = ConnectionState.thermal_lockout
            device.operational_state = OperationalState.locked_out
            device.model_loaded = ""
            device.active_task_id = ""

        self.save_device(device)
        return device

    # ── Thermal events ───────────────────────────────────────

    def record_thermal_event(self, event: ThermalEvent) -> None:
        with self._lock():
            self.THERMAL_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(self.THERMAL_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.model_dump(mode="json"), default=str) + "\n")
        logger.warning(
            "Thermal %s on %s: %s=%.1f (threshold=%.1f)",
            event.event_type,
            event.device_id,
            event.trigger_sensor,
            event.trigger_value,
            event.trigger_threshold,
        )

    def get_thermal_history(
        self, device_id: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        if not self.THERMAL_LOG.exists():
            return []
        events: List[Dict[str, Any]] = []
        for line in self.THERMAL_LOG.read_text(encoding="utf-8").strip().splitlines():
            try:
                evt = json.loads(line)
                if device_id is None or evt.get("device_id") == device_id:
                    events.append(evt)
            except json.JSONDecodeError:
                continue
        return events[-limit:]

    # ── Status summary ───────────────────────────────────────

    def get_status(self, mesh_enabled: bool) -> MeshStatus:
        devices = self.list_devices()
        by_mode: Dict[str, int] = {}
        connected = 0
        for d in devices:
            mode_key = d.device_mode.value
            by_mode[mode_key] = by_mode.get(mode_key, 0) + 1
            if d.connection_state in (
                ConnectionState.connected,
                ConnectionState.approved,
            ):
                connected += 1
        return MeshStatus(
            mesh_enabled=mesh_enabled,
            device_count=len(devices),
            devices_by_mode=by_mode,
            devices_connected=connected,
        )

    # ── Eligible devices for task dispatch ────────────────────

    def get_eligible_devices(self, mesh_enabled: bool) -> List[MeshDeviceInfo]:
        return [d for d in self.list_devices() if d.can_execute(mesh_enabled)]
