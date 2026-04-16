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


class DeviceCapabilities(BaseModel):
    """Hardware profile — collected once at boot, sent with heartbeat."""
    arch: str = ""                    # arm64-v8a, armeabi-v7a, x86_64
    cpu_cores: int = 0
    ram_total_mb: int = 0
    storage_free_mb: int = 0
    api_level: int = 0                # Android SDK_INT (0 for non-Android)
    soc_model: str = ""
    has_gpu_compute: bool = False     # Vulkan / OpenCL support
    max_file_descriptors: int = 1024
    # BUGS_LATENTES §H12 — runtimes que el device reporta poder ejecutar.
    # Probed dinámicamente por HardwareMonitorService (Python) o por el
    # adapter nativo (Android Kotlin) antes del enrollment. Valores típicos:
    # "python_native", "wasm", "micro_c", "web". Vacío = incapaz de ejecutar
    # ningún runtime del catálogo → solo rol de client/sensor en la mesh.
    supported_runtimes: list[str] = Field(default_factory=list)


class WorkspaceRole(str, Enum):
    owner = "owner"
    member = "member"


class Workspace(BaseModel):
    """A workspace groups devices into an isolated session.

    INV-L1: Every workspace is bound to the GIMO Core license that created it.
    ``license_key_hash`` stores SHA-256 of the license key at creation time.
    If the Core's license changes or expires, the workspace becomes inert.
    """
    workspace_id: str
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    owner_device_id: str = ""
    license_key_hash: str = ""  # INV-L1: SHA-256 of ORCH_LICENSE_KEY at creation


class WorkspaceMembership(BaseModel):
    """Per-workspace device configuration (INV-W3: mode is per-workspace)."""
    workspace_id: str
    device_id: str
    role: WorkspaceRole = WorkspaceRole.member
    device_mode: DeviceMode = DeviceMode.inference
    joined_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PairingCode(BaseModel):
    """Ephemeral code to join a workspace (INV-S3: max 5 min TTL, single-use)."""
    code: str
    workspace_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    used: bool = False
    used_by: Optional[str] = None


class MeshDeviceInfo(BaseModel):
    device_id: str
    name: str = ""
    device_secret: str = ""  # HMAC secret for heartbeat authentication
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
    inference_endpoint: str = ""
    capabilities: Optional[DeviceCapabilities] = None
    active_workspace_id: str = "default"  # INV-W2: exactly 1 workspace active

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
    device_secret: str = ""  # Must match enrolled device_secret
    device_mode: DeviceMode = DeviceMode.inference
    operational_state: OperationalState = OperationalState.idle
    device_class: str = "desktop"
    soc_model: str = ""
    soc_vendor: str = ""
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
    inference_endpoint: str = ""
    mode_locked: bool = False  # True = user locked mode, Core cannot change it
    capabilities: Optional[DeviceCapabilities] = None
    workspace_id: str = "default"  # INV-W1: heartbeat reports active workspace


# --- Utility Task System ---

class TaskStatus(str, Enum):
    pending = "pending"
    assigned = "assigned"
    running = "running"
    completed = "completed"
    failed = "failed"
    timed_out = "timed_out"


class UtilityTaskType(str, Enum):
    ping = "ping"
    text_validate = "text_validate"
    text_transform = "text_transform"
    json_validate = "json_validate"
    shell_exec = "shell_exec"
    file_read = "file_read"
    file_hash = "file_hash"


# Default hardware requirements per task type
TASK_TYPE_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "ping": {"min_ram_mb": 0},
    "text_validate": {"min_ram_mb": 64},
    "text_transform": {"min_ram_mb": 64},
    "json_validate": {"min_ram_mb": 128},
    "shell_exec": {"min_ram_mb": 256},
    "file_read": {"min_ram_mb": 128},
    "file_hash": {"min_ram_mb": 256},
}


class MeshTask(BaseModel):
    task_id: str
    task_type: UtilityTaskType
    workspace_id: str = "default"  # INV-W1/T2: task belongs to exactly 1 workspace
    payload: Dict[str, Any] = Field(default_factory=dict)
    assigned_device_id: str = ""
    status: TaskStatus = TaskStatus.pending
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    timeout_seconds: int = 60
    result: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    min_ram_mb: int = 0
    min_api_level: int = 0
    requires_arch: str = ""


class TaskResult(BaseModel):
    task_id: str
    device_id: str
    device_secret: str = ""
    status: Literal["completed", "failed"]
    result: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    duration_ms: int = 0
