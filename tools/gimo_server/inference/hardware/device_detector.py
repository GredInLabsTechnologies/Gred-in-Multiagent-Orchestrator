"""Deep hardware capability detection for the GIMO Inference Engine.

Extends the lightweight ``HardwareMonitorService`` detection with:
- Memory bandwidth estimation (crucial for LLM token throughput)
- Real TOPS figures for NPUs
- Execution provider mapping per device
- Unified memory detection for APUs

Results are cached for 30 s because hardware doesn't change in runtime.
"""
from __future__ import annotations

import logging
import platform
import subprocess
import time
from typing import List, Optional

from ..contracts import (
    DeviceCapability,
    ExecutionProviderType,
    HardwareTarget,
)

logger = logging.getLogger("gie.hardware.detector")

_CACHE_TTL = 30.0  # seconds


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------
_cache: Optional[List[DeviceCapability]] = None
_cache_ts: float = 0.0


def get_devices(force_refresh: bool = False) -> List[DeviceCapability]:
    """Return detected devices (cached for 30 s).

    Returns at least one entry (always the CPU).
    """
    global _cache, _cache_ts
    now = time.monotonic()
    if not force_refresh and _cache is not None and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    devices: List[DeviceCapability] = []
    devices.append(_detect_cpu())
    gpu = _detect_gpu()
    if gpu is not None:
        devices.append(gpu)
    npu = _detect_npu()
    if npu is not None:
        devices.append(npu)

    _cache = devices
    _cache_ts = now
    logger.info(
        "Devices detected: %s",
        [f"{d.device_type.value}:{d.device_name}" for d in devices],
    )
    return devices


# ---------------------------------------------------------------------------
# CPU detection
# ---------------------------------------------------------------------------

def _detect_cpu() -> DeviceCapability:
    import psutil

    mem = psutil.virtual_memory()
    total_gb = mem.total / 1024**3
    free_gb = mem.available / 1024**3
    psutil.cpu_count(logical=False) or 1

    # RAM bandwidth estimation by DDR type (conservative defaults):
    # DDR4-3200: ~51 GB/s,  DDR5-4800: ~76 GB/s,  LPDDR5X-6400: ~102 GB/s
    # We cannot detect DDR type reliably cross-platform, so use a safe floor.
    bandwidth_gbps = _estimate_cpu_bandwidth()

    # Available ORT EPs for CPU (always available).
    providers = [ExecutionProviderType.CPU]
    try:
        import onnxruntime as ort  # type: ignore[import]
        available = ort.get_available_providers()
        if "OpenVINOExecutionProvider" in available:
            providers.insert(0, ExecutionProviderType.OPENVINO)
    except Exception:
        pass

    # CPU can do INT8 via VNNI (AVX-512 VNNI or ARM dotprod).
    # We approximate based on x86/ARM architecture.
    machine = platform.machine().lower()
    supports_int8 = "x86" in machine or "amd64" in machine or "arm" in machine or "aarch64" in machine

    return DeviceCapability(
        device_type=HardwareTarget.CPU,
        device_name=_cpu_name(),
        total_memory_gb=round(total_gb, 2),
        free_memory_gb=round(free_gb, 2),
        compute_tops=0.0,  # not meaningful for CPU; use memory_bandwidth instead
        memory_bandwidth_gbps=bandwidth_gbps,
        supports_int8=supports_int8,
        supports_bf16=_cpu_supports_bf16(),
        supports_int4=False,
        execution_providers=providers,
        is_unified_memory=False,  # overridden when NPU is also present on APU
    )


def _cpu_name() -> str:
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Processor).Name"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        elif platform.system() == "Linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "Unknown CPU"


def _estimate_cpu_bandwidth() -> float:
    """Return a conservative DDR bandwidth estimate in GB/s."""
    # 48 GB/s is a safe floor for DDR4-3200 dual-channel, which is the most
    # common configuration for gaming / workstation PCs in 2024–2025.
    return 48.0


def _cpu_supports_bf16() -> bool:
    """Detect AVX-512 BF16 or ARM BF16 support."""
    try:
        if platform.system() == "Linux":
            with open("/proc/cpuinfo") as f:
                flags = " ".join(f.readlines())
            return "avx512_bf16" in flags or "bf16" in flags
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# GPU detection
# ---------------------------------------------------------------------------

def _detect_gpu() -> Optional[DeviceCapability]:
    """Try NVIDIA → AMD → Intel in order, return None if no GPU found."""
    cap = _try_nvidia()
    if cap:
        return cap
    cap = _try_amd_or_intel_gpu()
    return cap


def _try_nvidia() -> Optional[DeviceCapability]:
    try:
        import pynvml  # type: ignore[import]
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(handle)
        if hasattr(name, "decode"):
            name = name.decode()
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        total_gb = mem.total / 1024**3
        free_gb = mem.free / 1024**3
        try:
            temp = float(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
        except Exception:
            temp = 0.0
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            utilization = float(util.gpu)
        except Exception:
            utilization = 0.0
        try:
            cc = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
            compute_capability = cc[0] + cc[1] / 10
        except Exception:
            compute_capability = 0.0

        pynvml.nvmlShutdown()

        # Bandwidth estimation: SM count × SM clock × memory bus width × 2 / 8
        # Approximate using known cards by name keyword.
        bandwidth = _nvidia_bandwidth_estimate(name, total_gb)
        # TFLOPS (FP16): rough estimate for consumer cards.
        tflops = _nvidia_tflops_estimate(name, total_gb)

        providers = [
            ExecutionProviderType.CUDA,
            ExecutionProviderType.TENSORRT,
            ExecutionProviderType.CPU,
        ]

        return DeviceCapability(
            device_type=HardwareTarget.GPU,
            device_name=name,
            total_memory_gb=round(total_gb, 2),
            free_memory_gb=round(free_gb, 2),
            compute_tops=tflops,
            memory_bandwidth_gbps=bandwidth,
            supports_int8=compute_capability >= 6.1,
            supports_bf16=compute_capability >= 8.0,
            supports_int4=compute_capability >= 8.9,
            execution_providers=providers,
            is_unified_memory=False,
            temperature_celsius=temp,
            utilization_percent=utilization,
        )
    except Exception:
        return None


def _nvidia_bandwidth_estimate(name: str, vram_gb: float) -> float:
    """Very rough memory bandwidth (GB/s) for NVIDIA consumer GPUs."""
    n = name.lower()
    if "4090" in n:
        return 1008.0
    if "4080" in n:
        return 717.0
    if "4070" in n:
        return 504.0 if "super" not in n and "ti" not in n else 432.0
    if "3090" in n:
        return 936.0
    if "3080" in n:
        return 760.0 if "ti" not in n else 912.0
    if "3070" in n:
        return 448.0
    # Generic estimate: 100 GB/s per 8 GB VRAM (conservative for mid-range)
    return max(200.0, vram_gb * 25.0)


def _nvidia_tflops_estimate(name: str, vram_gb: float) -> float:
    """FP16 TFLOPS estimate for NVIDIA consumer GPUs."""
    n = name.lower()
    if "4090" in n: return 165.0
    if "4080" in n: return 97.0
    if "4070 ti" in n or "4070ti" in n: return 80.0
    if "4070" in n: return 56.0
    if "3090" in n: return 71.0
    if "3080 ti" in n or "3080ti" in n: return 68.0
    if "3080" in n: return 59.0
    if "3070" in n: return 41.0
    return max(10.0, vram_gb * 3.0)


def _try_amd_or_intel_gpu() -> Optional[DeviceCapability]:
    """Fallback detection via PowerShell / subprocess for AMD/Intel GPUs."""
    try:
        system = platform.system()
        if system == "Windows":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | "
                 "Select-Object Name,AdapterRAM,CurrentRefreshRate | ConvertTo-Json"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            import json
            data = json.loads(result.stdout)
            if isinstance(data, list):
                data = data[0]
            name: str = data.get("Name", "Unknown GPU")
            vram_bytes: int = data.get("AdapterRAM") or 0
            vram_gb = vram_bytes / 1024**3

            name_lower = name.lower()
            if "amd" in name_lower or "radeon" in name_lower:
                providers = [ExecutionProviderType.ROCM, ExecutionProviderType.DIRECTML, ExecutionProviderType.CPU]
                vendor_specific_bw = vram_gb * 20.0  # rough
            elif "intel" in name_lower and "arc" in name_lower:
                providers = [ExecutionProviderType.DIRECTML, ExecutionProviderType.CPU]
                vendor_specific_bw = vram_gb * 15.0
            else:
                return None

            return DeviceCapability(
                device_type=HardwareTarget.GPU,
                device_name=name,
                total_memory_gb=round(vram_gb, 2),
                free_memory_gb=round(vram_gb * 0.85, 2),  # estimate
                compute_tops=vram_gb * 2.0,  # rough estimate
                memory_bandwidth_gbps=vendor_specific_bw,
                supports_int8=True,
                supports_bf16=False,
                supports_int4=False,
                execution_providers=providers,
                is_unified_memory=False,
            )
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# NPU detection
# ---------------------------------------------------------------------------

def _detect_npu() -> Optional[DeviceCapability]:
    """Detect AMD XDNA or Intel Core Ultra NPU."""
    try:
        system = platform.system()
        if system == "Windows":
            return _detect_npu_windows()
        elif system == "Linux":
            return _detect_npu_linux()
    except Exception as exc:
        logger.debug("NPU detection error: %s", exc)
    return None


def _detect_npu_windows() -> Optional[DeviceCapability]:
    import json as _json
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores | ConvertTo-Json"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return None
        data = _json.loads(result.stdout)
        if isinstance(data, list):
            data = data[0]
        cpu_name: str = str(data.get("Name", "")).lower()
        return _npu_from_cpu_name(cpu_name)
    except Exception:
        return None


def _detect_npu_linux() -> Optional[DeviceCapability]:
    try:
        with open("/proc/cpuinfo") as f:
            cpu_name = " ".join(f.readlines()).lower()
        return _npu_from_cpu_name(cpu_name)
    except Exception:
        return None


def _npu_from_cpu_name(cpu_name: str) -> Optional[DeviceCapability]:
    """Construct a DeviceCapability for the NPU based on CPU model string."""
    import psutil
    mem = psutil.virtual_memory()
    total_gb = mem.total / 1024**3
    free_gb = mem.available / 1024**3

    # AMD Ryzen AI / XDNA family
    amd_keywords = ("ryzen ai", "z1", "z2", "strix", "hawk point", "phoenix", "rembrandt r")
    intel_keywords = ("core ultra", "meteor lake", "lunar lake", "arrow lake")

    if any(k in cpu_name for k in amd_keywords):
        if "z1 extreme" in cpu_name or "phoenix" in cpu_name:
            tops, model_name = 16.0, "AMD XDNA (Z1 Extreme / Phoenix)"
        elif "strix" in cpu_name or "halo" in cpu_name:
            tops, model_name = 50.0, "AMD XDNA2 (Strix / Halo)"
        else:
            tops, model_name = 10.0, "AMD XDNA (Ryzen AI)"

        # AMD APU: GPU and CPU share high-bandwidth LPDDR memory.
        is_unified = True
        # NPU on AMD XDNA uses VitisAI EP; fallback to OpenVINO / CPU.
        providers = [ExecutionProviderType.VITIS_AI, ExecutionProviderType.CPU]
        # Try to detect VitisAI EP from ORT.
        try:
            import onnxruntime as ort  # type: ignore[import]
            available = ort.get_available_providers()
            if "VitisAIExecutionProvider" not in available:
                providers = [ExecutionProviderType.CPU]
        except Exception:
            providers = [ExecutionProviderType.CPU]

        return DeviceCapability(
            device_type=HardwareTarget.NPU,
            device_name=model_name,
            total_memory_gb=round(total_gb, 2),   # shares system RAM
            free_memory_gb=round(free_gb * 0.3, 2),  # allocate ~30% to NPU
            compute_tops=tops,
            memory_bandwidth_gbps=102.0,  # LPDDR5X-6400 typical for Z1 Extreme
            supports_int8=True,
            supports_bf16=False,
            supports_int4=tops >= 50.0,  # XDNA2 supports INT4
            execution_providers=providers,
            is_unified_memory=is_unified,
        )

    if any(k in cpu_name for k in intel_keywords):
        providers = [ExecutionProviderType.OPENVINO, ExecutionProviderType.CPU]
        try:
            import onnxruntime as ort  # type: ignore[import]
            available = ort.get_available_providers()
            if "OpenVINOExecutionProvider" not in available:
                providers = [ExecutionProviderType.CPU]
        except Exception:
            providers = [ExecutionProviderType.CPU]

        tops = 11.0  # Intel NPU baseline; Meteor Lake = 10 TOPS, Lunar Lake = 48 TOPS
        if "lunar lake" in cpu_name:
            tops = 48.0
        elif "arrow lake" in cpu_name:
            tops = 13.0

        return DeviceCapability(
            device_type=HardwareTarget.NPU,
            device_name="Intel NPU (Core Ultra)",
            total_memory_gb=round(total_gb, 2),
            free_memory_gb=round(free_gb * 0.2, 2),
            compute_tops=tops,
            memory_bandwidth_gbps=76.8,  # LPDDR5-4800 dual-channel
            supports_int8=True,
            supports_bf16=False,
            supports_int4=False,
            execution_providers=providers,
            is_unified_memory=True,
        )

    return None
