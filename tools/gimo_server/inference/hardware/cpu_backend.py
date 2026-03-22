"""CPU backend configuration and throughput estimation.

Provides ORT session-option recommendations and throughput estimates for
CPU-only inference so the scheduler can make informed routing decisions.
"""
from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass
from typing import Any, Dict

from ..contracts import DeviceCapability

logger = logging.getLogger("gie.hardware.cpu")


@dataclass
class CpuConfig:
    """Recommended configuration for CPU inference."""
    intra_op_threads: int
    inter_op_threads: int
    execution_mode: str          # "parallel" or "sequential"
    memory_arena: bool
    enable_mem_pattern: bool
    numa_aware: bool
    estimated_tps: float         # tokens per second for a 7B Q4 model


def get_cpu_config(device: DeviceCapability) -> CpuConfig:
    """Compute optimal CPU inference configuration.

    Uses physical core count (no HT) for inference threads since hyperthreaded
    cores share execution units and don't improve throughput for matrix ops.
    """
    physical_cores = _physical_cores()
    # For ORT: intra-op = cores used within one op (e.g., GEMM parallelism).
    # inter-op = ops that can run in parallel (usually low for sequential LLM).
    intra_threads = physical_cores
    inter_threads = max(1, physical_cores // 4)

    numa_aware = _has_numa()

    estimated_tps = _estimate_tps(device)

    return CpuConfig(
        intra_op_threads=intra_threads,
        inter_op_threads=inter_threads,
        execution_mode="parallel",
        memory_arena=True,
        enable_mem_pattern=True,
        numa_aware=numa_aware,
        estimated_tps=estimated_tps,
    )


def estimate_tps(param_billions: float, cores: int) -> float:
    """Estimate tokens-per-second for an INT8/INT4 model on CPU.

    Formula from the plan:  tps ≈ cores * 2.5 / param_billions
    This is calibrated for x86 VNNI INT8 inference on a mid-range desktop.
    """
    if param_billions <= 0:
        return 0.0
    return (cores * 2.5) / param_billions


def provider_options() -> Dict[str, Any]:
    """Return ORT CPUExecutionProvider options dict."""
    physical_cores = _physical_cores()
    return {
        # ORT uses this hint for thread-pool sizing.
        "CPUExecutionProvider": {
            "intra_op_num_threads": physical_cores,
        }
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _physical_cores() -> int:
    try:
        import psutil
        return psutil.cpu_count(logical=False) or os.cpu_count() or 4
    except Exception:
        return os.cpu_count() or 4


def _has_numa() -> bool:
    """Check for NUMA topology (relevant for multi-socket servers)."""
    try:
        if platform.system() == "Linux":
            result = os.listdir("/sys/devices/system/node/")
            numa_nodes = [d for d in result if d.startswith("node")]
            return len(numa_nodes) > 1
    except Exception:
        pass
    return False


def _estimate_tps(device: DeviceCapability) -> float:
    """Estimate tokens/sec for a generic 7B INT4 model using available RAM BW."""
    # Memory-bandwidth-bound estimation for autoregressive decoding:
    # bytes to move per token ≈ param_count * bytes_per_param
    # For 7B INT4: 7e9 * 0.5 = 3.5 GB; at 48 GB/s → ~13 tok/s (rough)
    bw = device.memory_bandwidth_gbps or 48.0
    model_gb = 7 * 0.5  # 7B INT4
    return round(bw / model_gb, 1)
