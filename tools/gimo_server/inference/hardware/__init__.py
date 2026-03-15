"""GIMO Inference Engine — Hardware Backends.

Public API::

    from inference.hardware import get_devices
    from inference.hardware import get_cpu_config, get_gpu_config, get_npu_config
    from inference.hardware import plan_unified_memory
"""
from .cpu_backend import CpuConfig, get_cpu_config, estimate_tps as cpu_estimate_tps
from .device_detector import get_devices
from .gpu_backend import GpuConfig, get_gpu_config, estimate_tps as gpu_estimate_tps
from .npu_backend import NpuConfig, get_npu_config, npu_can_handle
from .unified_memory_manager import UnifiedMemoryPlan, plan_unified_memory

__all__ = [
    "get_devices",
    "CpuConfig",
    "get_cpu_config",
    "cpu_estimate_tps",
    "GpuConfig",
    "get_gpu_config",
    "gpu_estimate_tps",
    "NpuConfig",
    "get_npu_config",
    "npu_can_handle",
    "UnifiedMemoryPlan",
    "plan_unified_memory",
]
