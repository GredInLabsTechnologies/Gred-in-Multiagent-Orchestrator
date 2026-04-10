"""Heartbeat client — sends periodic status to GIMO Core."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

from .config import AgentConfig
from .thermal import ThermalGuard, ThermalPhase

logger = logging.getLogger("gimo_mesh_agent.heartbeat")


class HeartbeatClient:
    """Sends periodic heartbeats to GIMO Core's /ops/mesh/heartbeat endpoint."""

    def __init__(
        self,
        config: AgentConfig,
        thermal_guard: ThermalGuard,
    ) -> None:
        self._config = config
        self._thermal = thermal_guard
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._active_task_id: str = ""
        self._model_loaded: str = ""
        self._device_mode: str = "inference"

    def set_active_task(self, task_id: str) -> None:
        self._active_task_id = task_id

    def set_model_loaded(self, model: str) -> None:
        self._model_loaded = model

    def set_device_mode(self, mode: str) -> None:
        self._device_mode = mode

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Heartbeat started (interval=%ds)", self._config.heartbeat_interval_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Heartbeat stopped")

    def _build_payload(self) -> Dict[str, Any]:
        from tools.gimo_server.services.hardware_monitor_service import HardwareMonitorService
        hw = HardwareMonitorService.get_instance()
        snap = hw.get_snapshot()

        # Determine operational state
        op_state = "idle"
        if self._thermal.is_locked_out:
            op_state = "locked_out"
        elif self._active_task_id:
            op_state = "busy"

        return {
            "device_id": self._config.device_id,
            "device_mode": self._device_mode,
            "connection_state": "connected",
            "operational_state": op_state,
            "device_class": snap.device_class,
            "soc_model": snap.soc_model,
            "max_model_params_b": snap.max_model_params_b,
            "model_loaded": self._model_loaded if not self._thermal.is_locked_out else "",
            "health_score": 100.0,
            "cpu_percent": snap.cpu_percent,
            "ram_percent": snap.ram_percent,
            "cpu_temp_c": snap.cpu_temp_c,
            "gpu_temp_c": snap.gpu_temp_c,
            "battery_percent": snap.battery_percent,
            "battery_charging": snap.battery_charging,
            "battery_temp_c": snap.battery_temp_c,
            "thermal_throttled": self._thermal.phase in (ThermalPhase.throttle, ThermalPhase.lockout),
            "thermal_locked_out": self._thermal.is_locked_out,
            "active_task_id": self._active_task_id if not self._thermal.is_locked_out else "",
        }

    async def _send_heartbeat(self) -> bool:
        payload = self._build_payload()
        url = f"{self._config.core_url}/ops/mesh/heartbeat"
        headers = {"Authorization": f"Bearer {self._config.auth_token}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    return True
                logger.warning("Heartbeat failed: %d %s", resp.status_code, resp.text[:200])
                return False
        except Exception as exc:
            logger.warning("Heartbeat error: %s", exc)
            return False

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._send_heartbeat()
            except Exception:
                logger.exception("Heartbeat loop error")
            await asyncio.sleep(self._config.heartbeat_interval_s)
