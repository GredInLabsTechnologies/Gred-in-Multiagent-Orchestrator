from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AgentConfig:
    """Configuration for the GIMO Mesh Device Agent."""

    # Core identity
    device_id: str = ""
    device_name: str = ""
    core_url: str = "http://localhost:9325"
    auth_token: str = ""

    # Modes
    allow_inference: bool = True
    allow_utility: bool = True
    allow_server: bool = False

    # Local control
    allow_core_control: bool = True
    allow_task_execution: bool = True

    # Heartbeat
    heartbeat_interval_s: int = 30

    # Thermal thresholds (Celsius)
    thermal_warn_cpu: float = 75.0
    thermal_warn_gpu: float = 80.0
    thermal_warn_battery: float = 40.0
    thermal_throttle_cpu: float = 85.0
    thermal_throttle_gpu: float = 90.0
    thermal_throttle_battery: float = 45.0
    thermal_lockout_cpu: float = 95.0
    thermal_lockout_gpu: float = 95.0
    thermal_lockout_battery: float = 50.0

    # Data directory
    data_dir: str = ""

    @classmethod
    def from_env(cls) -> AgentConfig:
        return cls(
            device_id=os.environ.get("GIMO_DEVICE_ID", ""),
            device_name=os.environ.get("GIMO_DEVICE_NAME", ""),
            core_url=os.environ.get("GIMO_CORE_URL", "http://localhost:9325"),
            auth_token=os.environ.get("GIMO_AUTH_TOKEN", ""),
            allow_inference=os.environ.get("GIMO_ALLOW_INFERENCE", "true").lower() == "true",
            allow_utility=os.environ.get("GIMO_ALLOW_UTILITY", "true").lower() == "true",
            allow_server=os.environ.get("GIMO_ALLOW_SERVER", "false").lower() == "true",
            allow_core_control=os.environ.get("GIMO_ALLOW_CORE_CONTROL", "true").lower() == "true",
            allow_task_execution=os.environ.get("GIMO_ALLOW_TASK_EXECUTION", "true").lower() == "true",
            heartbeat_interval_s=int(os.environ.get("GIMO_HEARTBEAT_INTERVAL", "30")),
            data_dir=os.environ.get("GIMO_AGENT_DATA_DIR", ""),
        )

    @property
    def resolved_data_dir(self) -> Path:
        if self.data_dir:
            return Path(self.data_dir)
        return Path.home() / ".gimo_mesh_agent"
