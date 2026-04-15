"""Hardware monitoring service for intelligent local LLM regulation."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import time
import subprocess
from collections import deque
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Literal, Optional

import psutil

from ..config import OPS_DATA_DIR

logger = logging.getLogger("orchestrator.hardware")

LoadLevel = Literal["safe", "caution", "critical"]

DEFAULT_THRESHOLDS = {
    "safe":     {"cpu": 70, "ram": 75},
    "caution":  {"cpu": 85, "ram": 90},
    "critical": {"cpu": 96, "ram": 97},
}

LOG_DIR = OPS_DATA_DIR / "logs"


@dataclass
class HardwareSnapshot:
    cpu_percent: float
    ram_percent: float
    ram_available_gb: float
    timestamp: float
    gpu_vendor: str = "none"
    gpu_name: str = "none"
    gpu_vram_gb: float = 0.0
    gpu_vram_free_gb: float = 0.0
    gpu_temp: float = 0.0
    total_ram_gb: float = 0.0
    wsl2_available: bool = False
    installed_providers: list[str] = field(default_factory=list)
    npu_vendor: str = "none"
    npu_name: str = "none"
    npu_tops: float = 0.0
    unified_memory: bool = False       # True for APU/SoC with high-bandwidth unified memory
    cpu_inference_capable: bool = False  # True if RAM+CPU can handle CPU-offload inference
    # GIE deep device capabilities (populated lazily by DeviceDetector)
    devices: list = field(default_factory=list)  # list[DeviceCapability]

    # Mobile / device classification
    device_class: str = "desktop"          # "desktop" | "laptop" | "smartphone" | "tablet" | "sbc"
    soc_model: str = ""                    # "Snapdragon 855" | "Exynos 2100" | ""
    soc_vendor: str = ""                   # "qualcomm" | "samsung" | "apple" | "mediatek" | ""
    gpu_compute_api: str = ""              # "cuda" | "vulkan" | "metal" | "opencl" | ""
    max_model_params_b: float = 0.0        # estimated max model size (RAM available GB / 2 for Q4 GGUF)

    # Battery
    battery_percent: float = -1.0          # 0-100, -1 if not applicable
    battery_charging: bool = False
    battery_temp_c: float = -1.0           # -1 if not available

    # Thermal protection state
    thermal_throttled: bool = False        # true if any sensor above warning threshold
    thermal_locked_out: bool = False       # true if lockout active

    def to_dict(self) -> dict:
        return asdict(self)

def _detect_wsl2() -> bool:
    try:
        result = subprocess.run(["wsl.exe", "-l", "-v"], capture_output=True, text=True, timeout=2)
        return result.returncode == 0
    except Exception:
        return False


def _detect_device_class() -> str:
    """Detect the type of device we're running on."""
    system = platform.system().lower()

    # Android detection (Termux or native)
    if os.path.exists("/system/build.prop") or "ANDROID_ROOT" in os.environ:
        return "smartphone"  # conservative default; tablet detection requires screen size heuristic

    # iOS detection (jailbreak/sideload with Python)
    if os.path.exists("/var/mobile"):
        return "smartphone"

    # SBC detection (Raspberry Pi, etc.)
    if system == "linux" and os.path.exists("/proc/device-tree/model"):
        try:
            model = Path("/proc/device-tree/model").read_text(errors="ignore").lower()
            if "raspberry" in model or "orange pi" in model or "rock" in model:
                return "sbc"
        except Exception:
            pass

    # Laptop detection: has battery on desktop OS
    if system in ("linux", "darwin", "windows"):
        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                return "laptop"
        except Exception:
            pass

    return "desktop"


def _detect_soc_info() -> tuple[str, str]:
    """Detect SoC model and vendor on Android. Returns (model, vendor)."""
    if not (os.path.exists("/system/build.prop") or "ANDROID_ROOT" in os.environ):
        return ("", "")

    soc_model = ""
    soc_vendor = ""

    try:
        # Try getprop (available on Android)
        result = subprocess.run(
            ["getprop", "ro.board.platform"],
            capture_output=True, text=True, timeout=5
        )
        platform_name = result.stdout.strip().lower()

        if "sm" in platform_name or "msm" in platform_name or "sdm" in platform_name:
            soc_vendor = "qualcomm"
        elif "exynos" in platform_name:
            soc_vendor = "samsung"
        elif "mt" in platform_name:
            soc_vendor = "mediatek"

        # Try to get more specific model
        result2 = subprocess.run(
            ["getprop", "ro.hardware.chipname"],
            capture_output=True, text=True, timeout=5
        )
        soc_model = result2.stdout.strip() or platform_name

    except Exception:
        pass

    return (soc_model, soc_vendor)


def _read_battery_info() -> tuple[float, bool, float]:
    """Read battery info. Returns (percent, charging, temp_c). Uses -1 for unavailable."""
    # Try psutil first (works on laptops)
    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            return (battery.percent, battery.power_plugged or False, -1.0)
    except Exception:
        pass

    # Try Android sysfs
    try:
        capacity_path = Path("/sys/class/power_supply/battery/capacity")
        status_path = Path("/sys/class/power_supply/battery/status")
        temp_path = Path("/sys/class/power_supply/battery/temp")

        percent = -1.0
        charging = False
        temp_c = -1.0

        if capacity_path.exists():
            percent = float(capacity_path.read_text().strip())
        if status_path.exists():
            charging = status_path.read_text().strip().lower() in ("charging", "full")
        if temp_path.exists():
            temp_c = float(temp_path.read_text().strip()) / 10.0  # Android reports in tenths of degree

        if percent >= 0:
            return (percent, charging, temp_c)
    except Exception:
        pass

    return (-1.0, False, -1.0)


def _estimate_max_model_params(ram_available_gb: float) -> float:
    """Estimate max model size in billions of parameters (Q4 GGUF rule of thumb)."""
    if ram_available_gb <= 0:
        return 0.0
    return round(ram_available_gb / 2.0, 1)


def _detect_gpu_compute_api(gpu_vendor: str) -> str:
    """Determine GPU compute API from vendor string."""
    if gpu_vendor == "nvidia":
        return "cuda"
    elif gpu_vendor == "amd":
        return "vulkan"
    elif gpu_vendor == "apple":
        return "metal"
    return ""


def _detect_gpu() -> dict:
    info = {"vendor": "none", "name": "none", "vram": 0.0, "vram_free": 0.0, "gpu_temp": 0.0}
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(handle)
        if hasattr(name, "decode"):
            name = name.decode("utf-8")
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        info["vendor"] = "nvidia"
        info["name"] = name
        info["vram"] = round(mem.total / (1024**3), 2)
        info["vram_free"] = round(mem.free / (1024**3), 2)
        try:
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            info["gpu_temp"] = float(temp)
        except Exception:
            info["gpu_temp"] = 0.0
        pynvml.nvmlShutdown()
        return info
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            name = data.get("Name", "unknown")
            ram = data.get("AdapterRAM", 0)
            if ram is None: ram = 0
            
            vendor = "none"
            name_lower = name.lower()
            if "amd" in name_lower or "radeon" in name_lower:
                vendor = "amd"
            elif "intel" in name_lower:
                vendor = "intel"
            
            info["vendor"] = vendor
            info["name"] = name
            info["vram"] = round(float(ram) / (1024**3), 2)
            info["vram_free"] = info["vram"]
            return info
    except Exception:
        pass

    return info

def _detect_npu() -> dict:
    """Detect AMD XDNA / Intel NPU presence via WMI on Windows."""
    info: dict = {"vendor": "none", "name": "none", "tops": 0.0}
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores | ConvertTo-Json",
            ],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list):
                data = data[0]
            cpu_name = str(data.get("Name", "")).lower()
            # AMD Ryzen AI / Z-series with XDNA NPU
            if any(k in cpu_name for k in ("ryzen ai", "z1", "z2", "strix", "hawk point", "phoenix", "rembrandt r")):
                info["vendor"] = "amd_xdna"
                info["name"] = data.get("Name", "AMD Ryzen AI")
                # Z1 Extreme = 16 TOPS, Phoenix = 16 TOPS, Strix Halo = 50 TOPS
                if "z1 extreme" in cpu_name or "phoenix" in cpu_name:
                    info["tops"] = 16.0
                    info["unified_memory"] = True   # APU: shared high-bandwidth LPDDR5X
                elif "strix" in cpu_name or "halo" in cpu_name:
                    info["tops"] = 50.0
                    info["unified_memory"] = True
                else:
                    info["tops"] = 10.0
                    info["unified_memory"] = True
            # Intel Core Ultra NPU
            elif "core ultra" in cpu_name or "meteor lake" in cpu_name or "lunar lake" in cpu_name:
                info["vendor"] = "intel_npu"
                info["name"] = data.get("Name", "Intel Core Ultra")
                info["tops"] = 11.0
    except Exception:
        pass
    return info


def _get_installed_providers() -> list[str]:
    try:
        from .providers.service import ProviderService
        cfg = ProviderService.get_public_config()
        if cfg and cfg.providers:
            return list(cfg.providers.keys())
    except Exception:
        pass
    return []


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
        # Strong refs for fire-and-forget notification tasks (prevents premature GC).
        self._notification_tasks: set[asyncio.Task] = set()

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
        gpu_info = _detect_gpu()
        npu_info = _detect_npu()
        total_ram_gb = round(mem.total / (1024 ** 3), 2)
        ram_available_gb = round(mem.available / (1024 ** 3), 2)
        unified = bool(npu_info.get("unified_memory", False))
        # CPU inference capable: ≥16GB RAM + ≥4 cores (can run 7B Q4 at acceptable speed)
        cpu_infer = total_ram_gb >= 16.0 and (psutil.cpu_count(logical=False) or 0) >= 4

        # Mobile / mesh device detection
        device_class = _detect_device_class()
        soc_model, soc_vendor = _detect_soc_info()
        battery_pct, battery_charging, battery_temp = _read_battery_info()
        max_params = _estimate_max_model_params(ram_available_gb)
        gpu_compute_api = _detect_gpu_compute_api(gpu_info["vendor"])

        return HardwareSnapshot(
            cpu_percent=psutil.cpu_percent(interval=0.1),
            ram_percent=mem.percent,
            ram_available_gb=ram_available_gb,
            timestamp=time.time(),
            gpu_vendor=gpu_info["vendor"],
            gpu_name=gpu_info["name"],
            gpu_vram_gb=gpu_info["vram"],
            gpu_vram_free_gb=gpu_info["vram_free"],
            gpu_temp=gpu_info.get("gpu_temp", 0.0),
            total_ram_gb=total_ram_gb,
            wsl2_available=_detect_wsl2(),
            installed_providers=_get_installed_providers(),
            npu_vendor=npu_info["vendor"],
            npu_name=npu_info["name"],
            npu_tops=npu_info["tops"],
            unified_memory=unified,
            cpu_inference_capable=cpu_infer,
            device_class=device_class,
            soc_model=soc_model,
            soc_vendor=soc_vendor,
            gpu_compute_api=gpu_compute_api,
            max_model_params_b=max_params,
            battery_percent=battery_pct,
            battery_charging=battery_charging,
            battery_temp_c=battery_temp,
        )

    def get_load_level(self, snapshot: Optional[HardwareSnapshot] = None) -> LoadLevel:
        s = snapshot or (self._history[-1] if self._history else self.get_snapshot())
        t = self._thresholds
        if s.cpu_percent >= t["critical"]["cpu"] or s.ram_percent >= t["critical"]["ram"]:
            return "critical"
        if s.gpu_vram_gb > 0 and s.gpu_vram_free_gb < 0.5:
            return "critical"
        if s.cpu_percent >= t["caution"]["cpu"] or s.ram_percent >= t["caution"]["ram"]:
            return "caution"
        return "safe"

    def should_defer_run(self, weight: str = "medium") -> bool:
        """Check if a run should be deferred based on current load."""
        level = self.get_load_level()
        if level == "critical":
            return True
        if level == "caution" and weight == "heavy":
            return True
        return False

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
        await asyncio.sleep(0)  # Appease linter requiring async features

    async def stop_monitoring(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                current_loop = asyncio.get_running_loop()
                if self._task_loop is current_loop:
                    await self._task
            except asyncio.CancelledError:
                raise
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
        if new == "critical":
            try:
                from .notification_service import NotificationService
                import asyncio
                # Called from an async monitor loop — get_running_loop raises
                # RuntimeError if we somehow ended up outside a loop, which the
                # outer try/except swallows (fail-open: just skip the notify).
                asyncio.get_running_loop()
                _notify_task = asyncio.create_task(NotificationService.publish(
                    "system_degraded",
                    {"level": new, "cpu": snap.cpu_percent, "ram": snap.ram_percent,
                     "vram_free_gb": snap.gpu_vram_free_gb, "critical": True},
                ))
                self._notification_tasks.add(_notify_task)
                _notify_task.add_done_callback(self._notification_tasks.discard)
            except Exception:
                pass
