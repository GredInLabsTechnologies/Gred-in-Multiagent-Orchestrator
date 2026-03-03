"""Hardware monitoring service for intelligent local LLM regulation."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Literal, Optional

import psutil

from ..config import OPS_DATA_DIR

logger = logging.getLogger("orchestrator.hardware")

LoadLevel = Literal["safe", "caution", "critical"]

DEFAULT_THRESHOLDS = {
    "safe":     {"cpu": 60, "ram": 70},
    "caution":  {"cpu": 80, "ram": 85},
    "critical": {"cpu": 92, "ram": 93},
}

LOG_DIR = OPS_DATA_DIR / "logs"


@dataclass
class HardwareSnapshot:
    cpu_percent: float
    ram_percent: float
    ram_available_gb: float
    timestamp: float

    def to_dict(self) -> dict:
        return asdict(self)


class HardwareMonitorService:
    """Singleton that samples system state periodically."""

    _instance: Optional["HardwareMonitorService"] = None

    def __init__(self, thresholds: Optional[dict] = None, interval: float = 10.0):
        self._thresholds = thresholds or DEFAULT_THRESHOLDS
        self._interval = interval
        self._history: deque[HardwareSnapshot] = deque(maxlen=60)
        self._task: Optional[asyncio.Task] = None
        self._task_loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_level: LoadLevel = "safe"
        self._running = False

    @classmethod
    def get_instance(cls) -> "HardwareMonitorService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    def update_thresholds(self, thresholds: dict) -> None:
        merged = dict(DEFAULT_THRESHOLDS)
        for level in ("safe", "caution", "critical"):
            if level in thresholds:
                merged[level] = {**merged.get(level, {}), **thresholds[level]}
        self._thresholds = merged

    def get_snapshot(self) -> HardwareSnapshot:
        mem = psutil.virtual_memory()
        return HardwareSnapshot(
            cpu_percent=psutil.cpu_percent(interval=0.1),
            ram_percent=mem.percent,
            ram_available_gb=round(mem.available / (1024 ** 3), 2),
            timestamp=time.time(),
        )

    def get_load_level(self, snapshot: Optional[HardwareSnapshot] = None) -> LoadLevel:
        s = snapshot or (self._history[-1] if self._history else self.get_snapshot())
        t = self._thresholds
        if s.cpu_percent >= t["critical"]["cpu"] or s.ram_percent >= t["critical"]["ram"]:
            return "critical"
        if s.cpu_percent >= t["caution"]["cpu"] or s.ram_percent >= t["caution"]["ram"]:
            return "caution"
        return "safe"

    def is_local_safe(self, model_size_gb: Optional[float] = None) -> bool:
        level = self.get_load_level()
        if level == "critical":
            return False
        if level == "caution" and model_size_gb and model_size_gb > 4.0:
            return False
        return True

    def get_current_state(self) -> dict:
        s = self._history[-1] if self._history else self.get_snapshot()
        level = self.get_load_level(s)
        return {**s.to_dict(), "load_level": level}

    async def start_monitoring(self) -> None:
        if self._running:
            return
        self._running = True
        self._task_loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._loop())
        logger.info("Hardware monitoring started (interval=%ss)", self._interval)

    async def stop_monitoring(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                current_loop = asyncio.get_running_loop()
                if self._task_loop is current_loop:
                    await self._task
            except asyncio.CancelledError:
                pass
            except RuntimeError as exc:
                # Puede ocurrir en tests cuando el singleton se inicia en un loop
                # y se intenta cerrar en otro loop distinto.
                if "different loop" not in str(exc).lower():
                    raise
            self._task = None
            self._task_loop = None

    async def _loop(self) -> None:
        while self._running:
            try:
                snap = self.get_snapshot()
                self._history.append(snap)
                level = self.get_load_level(snap)
                if level != self._last_level:
                    self._on_level_change(self._last_level, level, snap)
                    self._last_level = level
            except Exception as e:
                logger.error("Hardware sample error: %s", e)
            await asyncio.sleep(self._interval)

    def _on_level_change(self, old: LoadLevel, new: LoadLevel, snap: HardwareSnapshot) -> None:
        logger.warning("Hardware load: %s -> %s (cpu=%.1f%%, ram=%.1f%%)",
                        old, new, snap.cpu_percent, snap.ram_percent)
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_path = LOG_DIR / "hardware_load.jsonl"
            entry = {"ts": snap.timestamp, "from": old, "to": new,
                     "cpu": snap.cpu_percent, "ram": snap.ram_percent}
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass
