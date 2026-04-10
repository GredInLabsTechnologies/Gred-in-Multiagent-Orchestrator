from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class DeviceMode(str, Enum):
    inference = "inference"
    utility = "utility"
    server = "server"
    hybrid = "hybrid"


class ConnectionState(str, Enum):
    offline = "offline"
    discoverable = "discoverable"
    pending_approval = "pending_approval"
    approved = "approved"
    refused = "refused"
    connected = "connected"
    reconnecting = "reconnecting"
    thermal_lockout = "thermal_lockout"


class OperationalState(str, Enum):
    idle = "idle"
    busy = "busy"
    paused = "paused"
    draining = "draining"
    disabled = "disabled"
    error = "error"
    locked_out = "locked_out"


class MeshDeviceInfo(BaseModel):
    device_id: str
    name: str = ""
    device_mode: DeviceMode = DeviceMode.inference
    connection_state: ConnectionState = ConnectionState.offline
    operational_state: OperationalState = OperationalState.idle
    core_enabled: bool = True
    local_allow_core_control: bool = True
    local_allow_task_execution: bool = True
    device_class: str = "desktop"
    soc_model: str = ""
    soc_vendor: str = ""
    max_model_params_b: float = 0.0
    model_loaded: str = ""
    last_heartbeat: Optional[datetime] = None
    enrolled_at: Optional[datetime] = None
    health_score: float = 100.0
    battery_percent: float = -1.0
    battery_charging: bool = False
    battery_temp_c: float = -1.0
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    cpu_temp_c: float = -1.0
    gpu_temp_c: float = -1.0
    thermal_throttled: bool = False
    thermal_locked_out: bool = False
    active_task_id: str = ""

    def can_execute(self, mesh_enabled: bool) -> bool:
        return (
            mesh_enabled
            and self.connection_state in (ConnectionState.approved, ConnectionState.connected)
            and self.core_enabled
            and self.local_allow_core_control
            and self.local_allow_task_execution
            and self.operational_state not in (
                OperationalState.disabled,
                OperationalState.paused,
                OperationalState.error,
                OperationalState.draining,
                OperationalState.locked_out,
            )
            and not self.thermal_locked_out
        )


class ThermalEvent(BaseModel):
    device_id: str
    event_type: Literal["warning", "throttle", "lockout"]
    trigger_sensor: str
    trigger_value: float
    trigger_threshold: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    task_id: str = ""
    task_fingerprint: str = ""
    model_loaded: str = ""
    duration_before_trigger_minutes: float = 0.0
    ram_usage_pct: float = 0.0
    battery_pct: float = -1.0
    battery_charging: bool = False


class TaskFingerprint(BaseModel):
    action_class: str = ""
    target_type: str = ""
    domain_hints: List[str] = Field(default_factory=list)
    estimated_complexity: Literal["trivial", "simple", "moderate", "complex"] = "simple"
    requires_context_kb: int = 0
    read_only: bool = False


class MeshStatus(BaseModel):
    mesh_enabled: bool = False
    device_count: int = 0
    devices_by_mode: Dict[str, int] = Field(default_factory=dict)
    devices_connected: int = 0


class EnrollmentToken(BaseModel):
    token: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    used: bool = False
    device_id: Optional[str] = None


class HeartbeatPayload(BaseModel):
    device_id: str
    device_mode: DeviceMode = DeviceMode.inference
    connection_state: ConnectionState = ConnectionState.connected
    operational_state: OperationalState = OperationalState.idle
    device_class: str = "desktop"
    soc_model: str = ""
    max_model_params_b: float = 0.0
    model_loaded: str = ""
    health_score: float = 100.0
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    cpu_temp_c: float = -1.0
    gpu_temp_c: float = -1.0
    battery_percent: float = -1.0
    battery_charging: bool = False
    battery_temp_c: float = -1.0
    thermal_throttled: bool = False
    thermal_locked_out: bool = False
    active_task_id: str = ""
