from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tools.gimo_server.models.mesh import (
    ConnectionState,
    DeviceMode,
    MeshDeviceInfo,
    OperationalState,
)
from tools.gimo_server.services.mesh.registry import MeshRegistry

logger = logging.getLogger("orchestrator.mesh.host_bootstrap")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AndroidHostBootstrapConfig:
    enabled: bool
    device_id: str
    device_name: str
    device_mode: DeviceMode
    device_class: str
    inference_endpoint: str

    @classmethod
    def from_env(cls) -> AndroidHostBootstrapConfig | None:
        enabled = os.environ.get("GIMO_MESH_HOST_ENABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if not enabled:
            return None

        device_id = os.environ.get("GIMO_MESH_HOST_DEVICE_ID", "").strip()
        if not device_id:
            logger.warning("Android host bootstrap enabled without device_id")
            return None

        raw_mode = os.environ.get("GIMO_MESH_HOST_DEVICE_MODE", "server").strip().lower()
        try:
            device_mode = DeviceMode(raw_mode)
        except ValueError:
            logger.warning("Ignoring Android host bootstrap with invalid device_mode=%r", raw_mode)
            return None

        return cls(
            enabled=True,
            device_id=device_id,
            device_name=os.environ.get("GIMO_MESH_HOST_DEVICE_NAME", device_id).strip() or device_id,
            device_mode=device_mode,
            device_class=os.environ.get("GIMO_MESH_HOST_DEVICE_CLASS", "smartphone").strip() or "smartphone",
            inference_endpoint=os.environ.get("GIMO_MESH_HOST_INFERENCE_ENDPOINT", "").strip(),
        )


class AndroidHostBootstrapService:
    """Registers the Android-hosted GIMO Core as an authoritative mesh device."""

    RUNTIME_FILE_NAME = "host_runtime.json"

    def __init__(self, registry: MeshRegistry) -> None:
        self._registry = registry

    @property
    def runtime_path(self) -> Path:
        return self._registry.MESH_DIR / self.RUNTIME_FILE_NAME

    def bootstrap_from_env(self) -> MeshDeviceInfo | None:
        config = AndroidHostBootstrapConfig.from_env()
        if config is None:
            return None
        return self.bootstrap(config)

    def bootstrap(self, config: AndroidHostBootstrapConfig) -> MeshDeviceInfo:
        existing = self._registry.get_device(config.device_id)
        if existing is None:
            device = self._registry.enroll_device(
                device_id=config.device_id,
                name=config.device_name,
                device_mode=config.device_mode,
                device_class=config.device_class,
            )
        else:
            device = existing.model_copy(deep=True)

        device.name = config.device_name
        device.device_mode = config.device_mode
        device.device_class = config.device_class
        device.connection_state = ConnectionState.connected
        device.operational_state = OperationalState.idle
        device.local_allow_core_control = True
        device.local_allow_task_execution = True
        device.inference_endpoint = (
            config.inference_endpoint if config.device_mode == DeviceMode.hybrid else ""
        )
        device.thermal_locked_out = False
        device.thermal_throttled = False
        device.active_task_id = ""
        device.last_heartbeat = _utcnow()
        if device.enrolled_at is None:
            device.enrolled_at = device.last_heartbeat

        self._registry.save_device(device)
        self._write_runtime_state(device)
        logger.info(
            "Android host bootstrap registered %s (mode=%s)",
            device.device_id,
            device.device_mode.value,
        )
        return device

    def _write_runtime_state(self, device: MeshDeviceInfo) -> None:
        payload = {
            "device_id": device.device_id,
            "device_mode": device.device_mode.value,
            "device_class": device.device_class,
            "connection_state": device.connection_state.value,
            "operational_state": device.operational_state.value,
            "inference_endpoint": device.inference_endpoint,
            "updated_at": _utcnow().isoformat(),
        }
        self.runtime_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
