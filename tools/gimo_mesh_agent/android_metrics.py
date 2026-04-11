"""Android-native metrics collector for GIMO Mesh Agent.

Uses Termux API + /proc/ for metrics without root or psutil.
Sources (per DEV_MESH_ARCHITECTURE.md §6.2):
- termux-battery-status for battery
- /proc/stat for CPU usage
- /proc/meminfo for RAM
- getprop for SoC identification
"""

from __future__ import annotations

import json
import re
import subprocess
import time


def _shell(cmd: str) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return ""


def _shell_json(cmd: str) -> dict:
    raw = _shell(cmd)
    try:
        return json.loads(raw)
    except Exception:
        return {}


def get_soc_info() -> dict:
    platform = _shell("getprop ro.board.platform")
    chipname = _shell("getprop ro.hardware.chipname")
    model = _shell("getprop ro.product.model")
    vendor = "unknown"
    chip = (chipname or platform).lower()
    if "exynos" in chip:
        vendor = "samsung"
    elif "msm" in chip or "sm" in chip or "sdm" in chip:
        vendor = "qualcomm"
    elif "mt" in chip:
        vendor = "mediatek"
    elif "tensor" in chip:
        vendor = "google"
    return {
        "soc_model": chipname or platform,
        "soc_vendor": vendor,
        "device_model": model,
    }


def get_cpu_percent() -> float:
    def _read():
        line = _shell("head -1 /proc/stat")
        if not line:
            return None
        parts = line.split()
        vals = [int(x) for x in parts[1:] if x.isdigit()]
        if len(vals) < 4:
            return None
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return sum(vals), idle

    s1 = _read()
    if not s1:
        return 0.0
    time.sleep(0.5)
    s2 = _read()
    if not s2:
        return 0.0
    total_d = s2[0] - s1[0]
    idle_d = s2[1] - s1[1]
    if total_d == 0:
        return 0.0
    return round((1.0 - idle_d / total_d) * 100, 1)


def get_memory() -> dict:
    raw = _shell("cat /proc/meminfo")
    info = {}
    for line in raw.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            nums = re.sub(r"[^\d]", "", val.strip())
            info[key.strip()] = int(nums) if nums else 0
    total = info.get("MemTotal", 1)
    available = info.get("MemAvailable", 0)
    used = total - available
    return {
        "ram_total_mb": round(total / 1024),
        "ram_used_mb": round(used / 1024),
        "ram_percent": round(used / total * 100, 1) if total else 0.0,
    }


def get_battery() -> dict:
    data = _shell_json("termux-battery-status")
    if not data:
        return {
            "battery_percent": -1.0,
            "battery_temp_c": -1.0,
            "battery_charging": False,
        }
    return {
        "battery_percent": float(data.get("percentage", -1)),
        "battery_temp_c": float(data.get("temperature", -1)),
        "battery_charging": data.get("status", "").upper() in ("CHARGING", "FULL"),
    }


def collect_all() -> dict:
    soc = get_soc_info()
    cpu = get_cpu_percent()
    mem = get_memory()
    bat = get_battery()
    return {
        **soc,
        "cpu_percent": cpu,
        **mem,
        **bat,
        # CPU/GPU temp not available without root on most Android devices
        # Thermal protection relies on heartbeat + server-side thermalservice polling
        "cpu_temp_c": -1.0,
        "gpu_temp_c": -1.0,
    }


if __name__ == "__main__":
    print(json.dumps(collect_all(), indent=2))
