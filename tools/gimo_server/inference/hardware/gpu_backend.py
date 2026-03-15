"""GPU backend configuration and throughput estimation.

Handles NVIDIA (CUDA/TensorRT), AMD (ROCm), and Intel Arc (DML) GPUs.
Provides VRAM management hints and tokens-per-second estimates so the
scheduler can decide which model fits and how many layers to offload.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from ..contracts import DeviceCapability, ExecutionProviderType, HardwareTarget

logger = logging.getLogger("gie.hardware.gpu")


@dataclass
class GpuConfig:
    """Recommended GPU inference configuration."""
    primary_ep: ExecutionProviderType
    fallback_ep: ExecutionProviderType
    use_tensorrt: bool
    fp16_enabled: bool
    int8_enabled: bool
    vram_pre_alloc_gb: float          # amount to reserve at session start
    estimated_tps: float              # tokens/sec for a 7B FP16 model
    max_concurrent_sessions: int      # VRAM-limited concurrency


def get_gpu_config(device: DeviceCapability) -> GpuConfig:
    """Compute optimal GPU inference configuration."""
    providers = device.execution_providers
    use_cuda = ExecutionProviderType.CUDA in providers
    use_rocm = ExecutionProviderType.ROCM in providers
    use_dml = ExecutionProviderType.DIRECTML in providers

    if use_cuda:
        primary = ExecutionProviderType.CUDA
        fallback = ExecutionProviderType.CPU
        use_trt = ExecutionProviderType.TENSORRT in providers
    elif use_rocm:
        primary = ExecutionProviderType.ROCM
        fallback = ExecutionProviderType.CPU
        use_trt = False
    elif use_dml:
        primary = ExecutionProviderType.DIRECTML
        fallback = ExecutionProviderType.CPU
        use_trt = False
    else:
        primary = ExecutionProviderType.CPU
        fallback = ExecutionProviderType.CPU
        use_trt = False

    # Estimate how many concurrent sessions we can hold.
    # A 7B FP16 model needs ~14 GB VRAM; Q4 needs ~4 GB.
    # For simplicity: 1 session if < 12 GB VRAM, 2 if >= 12 GB.
    max_sessions = 2 if device.total_memory_gb >= 12.0 else 1

    # Reserve 10% of VRAM for driver/system overhead.
    pre_alloc = device.total_memory_gb * 0.1

    estimated_tps = _estimate_gpu_tps(device)

    return GpuConfig(
        primary_ep=primary,
        fallback_ep=fallback,
        use_tensorrt=use_trt,
        fp16_enabled=device.supports_bf16 or use_cuda,
        int8_enabled=device.supports_int8,
        vram_pre_alloc_gb=round(pre_alloc, 2),
        estimated_tps=round(estimated_tps, 1),
        max_concurrent_sessions=max_sessions,
    )


def estimate_tps(
    memory_bandwidth_gbps: float,
    param_billions: float,
    bytes_per_param: float = 2.0,  # FP16
) -> float:
    """Estimate tokens/sec for GPU autoregressive decoding.

    Formula from the plan:
        tps ≈ memory_bandwidth_gbps * 0.5 / (param_billions * bytes_per_param)

    The 0.5 factor accounts for ~50% effective bandwidth utilisation.
    """
    model_gb = param_billions * bytes_per_param
    if model_gb <= 0:
        return 0.0
    return (memory_bandwidth_gbps * 0.5) / model_gb


def vram_required_gb(
    param_billions: float,
    bytes_per_param: float = 2.0,
    overhead_factor: float = 1.2,
) -> float:
    """Estimate VRAM needed to hold a model (weights only, no KV cache)."""
    return param_billions * bytes_per_param * overhead_factor


def provider_options_for_cuda(device_id: int = 0) -> Dict[str, Any]:
    """Standard CUDA EP options."""
    return {
        "device_id": device_id,
        "arena_extend_strategy": "kNextPowerOfTwo",
        "gpu_mem_limit": 0,
        "cudnn_conv_algo_search": "EXHAUSTIVE",
        "do_copy_in_default_stream": True,
    }


def provider_options_for_tensorrt(device_id: int = 0) -> Dict[str, Any]:
    """Standard TensorRT EP options."""
    return {
        "device_id": device_id,
        "trt_max_workspace_size": 1 << 30,  # 1 GB
        "trt_fp16_enable": True,
        "trt_int8_enable": False,
    }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _estimate_gpu_tps(device: DeviceCapability) -> float:
    """Estimate tokens/sec for a 7B FP16 model on this GPU."""
    bw = device.memory_bandwidth_gbps or 100.0
    # 7B FP16 = 14 GB; effective BW at 50%:
    return (bw * 0.5) / 14.0
