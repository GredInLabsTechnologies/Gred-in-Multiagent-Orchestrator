"""Shard planner — decides how to split an oversized model across devices.

This is the core algorithm that differentiates GIMO from Ollama/LM Studio:
instead of rejecting models that don't fit in a single device, we compute
the best shard strategy across GPU + CPU RAM + NPU + disk (mmap).

See the plan (section FASE 3) for the decision tree.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .contracts import (
    DeviceCapability,
    HardwareTarget,
    MemoryBudget,
    ModelSpec,
    ShardStrategy,
)

logger = logging.getLogger("gie.shard_planner")

# Safety margins per device type (fraction of total to keep free for OS/runtime)
_MARGIN_GPU  = 0.15   # keep 15% of VRAM free
_MARGIN_CPU  = 0.40   # keep 40% of RAM free (OS + browser etc.)
_MARGIN_DISK = 0.10   # keep 10% of available disk cache free


@dataclass
class LayerAllocation:
    """How many transformer layers go to each device."""
    gpu_layers: int = 0
    cpu_layers: int = 0
    npu_layers: int = 0   # embedding/attention heads on NPU
    disk_layers: int = 0  # memory-mapped from disk


@dataclass
class ShardPlan:
    """Complete sharding plan produced by the planner."""
    strategy: ShardStrategy
    layer_allocation: LayerAllocation = field(default_factory=LayerAllocation)
    # Byte allocation per device (for logging / scheduling).
    device_bytes: Dict[str, int] = field(default_factory=dict)
    # Total model size in bytes.
    model_bytes: int = 0
    # Human-readable explanation of the decision.
    rationale: str = ""
    # If REJECT: message explaining what hardware is needed.
    reject_reason: str = ""
    # Overhead ratio estimate: transfer_time / compute_time (0 = no offload)
    estimated_overhead_ratio: float = 0.0


def plan(
    spec: ModelSpec,
    budget: MemoryBudget,
    devices: List[DeviceCapability],
    *,
    allow_disk_offload: bool = True,
    max_oversized_ratio: float = 3.0,
) -> ShardPlan:
    """Compute the optimal shard strategy for *spec* given *budget*.

    Args:
        spec:                 Model descriptor including size and param count.
        budget:               Pre-calculated memory budget (see memory_manager).
        devices:              List of available devices (from device_detector).
        allow_disk_offload:   If False, reject models that need disk offload.
        max_oversized_ratio:  Reject if model > ratio * total_usable_memory.

    Returns:
        A :class:`ShardPlan` with strategy and layer allocations.
    """
    model_gb = spec.size_bytes / 1024**3
    model_bytes = spec.size_bytes

    gpu_avail  = budget.gpu_available_gb  * (1 - _MARGIN_GPU)
    cpu_avail  = budget.cpu_available_gb  * (1 - _MARGIN_CPU)
    npu_avail  = budget.npu_available_gb
    disk_avail = budget.disk_cache_gb     * (1 - _MARGIN_DISK)

    total_usable = gpu_avail + cpu_avail + npu_avail + disk_avail
    layer_size_gb = _layer_size_gb(spec)
    total_layers = spec.metadata.get("num_layers", 32)

    logger.debug(
        "ShardPlan: model=%.1f GB, gpu=%.1f, cpu=%.1f, npu=%.1f, disk=%.1f",
        model_gb, gpu_avail, cpu_avail, npu_avail, disk_avail,
    )

    # Hard reject: model is too large even with all devices + disk.
    if model_gb > total_usable * max_oversized_ratio:
        needed_gb = model_gb / max_oversized_ratio
        return ShardPlan(
            strategy=ShardStrategy.NONE,
            model_bytes=model_bytes,
            rationale="Model too large for available hardware",
            reject_reason=(
                f"Model requires {model_gb:.1f} GB but only "
                f"{total_usable:.1f} GB is usable. "
                f"Upgrade to a system with ≥{needed_gb:.0f} GB total memory."
            ),
        )

    # ----------------------------------------------------------------
    # CASE 1: fits entirely in GPU VRAM
    # ----------------------------------------------------------------
    if model_gb <= gpu_avail:
        return ShardPlan(
            strategy=ShardStrategy.NONE,
            layer_allocation=LayerAllocation(gpu_layers=total_layers),
            device_bytes={"gpu": model_bytes},
            model_bytes=model_bytes,
            rationale=f"Full GPU load ({model_gb:.1f} GB fits in {gpu_avail:.1f} GB VRAM)",
            estimated_overhead_ratio=0.0,
        )

    # ----------------------------------------------------------------
    # CASE 2: GPU + NPU (embedding/attention on NPU, FFN on GPU)
    # ----------------------------------------------------------------
    npu_device = next((d for d in devices if d.device_type == HardwareTarget.NPU), None)
    if npu_device and npu_avail > 0 and model_gb <= gpu_avail + npu_avail:
        npu_fraction = npu_avail / model_gb
        npu_layers = max(1, math.floor(npu_fraction * total_layers))
        gpu_layers = total_layers - npu_layers
        npu_bytes = int(model_bytes * npu_fraction)
        gpu_bytes = model_bytes - npu_bytes
        return ShardPlan(
            strategy=ShardStrategy.LAYER_SPLIT,
            layer_allocation=LayerAllocation(
                gpu_layers=gpu_layers,
                npu_layers=npu_layers,
            ),
            device_bytes={"gpu": gpu_bytes, "npu": npu_bytes},
            model_bytes=model_bytes,
            rationale=(
                f"NPU+GPU split: {npu_layers} layers on NPU (INT8), "
                f"{gpu_layers} layers on GPU"
            ),
            estimated_overhead_ratio=0.05,  # minimal — no disk IO
        )

    # ----------------------------------------------------------------
    # CASE 3: GPU + CPU RAM offload
    # ----------------------------------------------------------------
    if model_gb <= gpu_avail + cpu_avail:
        gpu_layers = max(0, math.floor(gpu_avail / layer_size_gb)) if layer_size_gb > 0 else total_layers
        gpu_layers = min(gpu_layers, total_layers)
        cpu_layers = total_layers - gpu_layers
        gpu_bytes = int(model_bytes * (gpu_layers / total_layers)) if total_layers else 0
        cpu_bytes = model_bytes - gpu_bytes
        overhead = _offload_overhead(gpu_layers, cpu_layers, spec.param_count_b)
        return ShardPlan(
            strategy=ShardStrategy.OFFLOAD_CPU,
            layer_allocation=LayerAllocation(gpu_layers=gpu_layers, cpu_layers=cpu_layers),
            device_bytes={"gpu": gpu_bytes, "cpu": cpu_bytes},
            model_bytes=model_bytes,
            rationale=(
                f"CPU offload: {gpu_layers} layers in VRAM, "
                f"{cpu_layers} layers in RAM"
            ),
            estimated_overhead_ratio=overhead,
        )

    # ----------------------------------------------------------------
    # CASE 4: GPU + NPU + CPU hybrid
    # ----------------------------------------------------------------
    if npu_device and npu_avail > 0 and model_gb <= gpu_avail + cpu_avail + npu_avail:
        npu_layers = max(1, total_layers // 4)     # embed + first attention heads
        gpu_layers = max(0, math.floor(gpu_avail / layer_size_gb)) if layer_size_gb else 0
        gpu_layers = min(gpu_layers, total_layers - npu_layers)
        cpu_layers = total_layers - gpu_layers - npu_layers
        gpu_bytes = int(model_bytes * (gpu_layers / total_layers)) if total_layers else 0
        npu_bytes = int(model_bytes * (npu_layers / total_layers)) if total_layers else 0
        cpu_bytes = model_bytes - gpu_bytes - npu_bytes
        overhead = _offload_overhead(gpu_layers, cpu_layers, spec.param_count_b)
        return ShardPlan(
            strategy=ShardStrategy.HYBRID,
            layer_allocation=LayerAllocation(
                gpu_layers=gpu_layers,
                cpu_layers=cpu_layers,
                npu_layers=npu_layers,
            ),
            device_bytes={"gpu": gpu_bytes, "cpu": cpu_bytes, "npu": npu_bytes},
            model_bytes=model_bytes,
            rationale=(
                f"Hybrid NPU+GPU+CPU: NPU={npu_layers}, GPU={gpu_layers}, CPU={cpu_layers}"
            ),
            estimated_overhead_ratio=max(overhead, 0.2),
        )

    # ----------------------------------------------------------------
    # CASE 5: disk offload (mmap)
    # ----------------------------------------------------------------
    if allow_disk_offload and model_gb <= gpu_avail + cpu_avail + disk_avail:
        gpu_layers = max(0, math.floor(gpu_avail / layer_size_gb)) if layer_size_gb else 0
        gpu_layers = min(gpu_layers, total_layers)
        cpu_layers = max(0, math.floor(cpu_avail / layer_size_gb)) if layer_size_gb else 0
        cpu_layers = min(cpu_layers, total_layers - gpu_layers)
        disk_layers = total_layers - gpu_layers - cpu_layers
        gpu_bytes  = int(model_bytes * (gpu_layers  / total_layers)) if total_layers else 0
        cpu_bytes  = int(model_bytes * (cpu_layers  / total_layers)) if total_layers else 0
        disk_bytes = model_bytes - gpu_bytes - cpu_bytes
        return ShardPlan(
            strategy=ShardStrategy.OFFLOAD_DISK,
            layer_allocation=LayerAllocation(
                gpu_layers=gpu_layers,
                cpu_layers=cpu_layers,
                disk_layers=disk_layers,
            ),
            device_bytes={"gpu": gpu_bytes, "cpu": cpu_bytes, "disk": disk_bytes},
            model_bytes=model_bytes,
            rationale=(
                f"Disk offload (mmap): GPU={gpu_layers}, CPU={cpu_layers}, "
                f"disk={disk_layers} layers — expect 2-5 tok/s"
            ),
            estimated_overhead_ratio=0.7,  # disk IO is the bottleneck
        )

    # ----------------------------------------------------------------
    # REJECT
    # ----------------------------------------------------------------
    return ShardPlan(
        strategy=ShardStrategy.NONE,
        model_bytes=model_bytes,
        rationale="Insufficient memory even with disk offload",
        reject_reason=(
            f"Model {spec.model_id} ({model_gb:.1f} GB) exceeds total usable memory "
            f"({total_usable:.1f} GB, disk offload {'disabled' if not allow_disk_offload else 'included'}). "
            "Consider a smaller quantization (Q4 instead of FP16) or a smaller model."
        ),
    )


def is_rejected(plan: ShardPlan) -> bool:
    """Return True if the plan represents a rejection (model cannot be loaded)."""
    return bool(plan.reject_reason)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _layer_size_gb(spec: ModelSpec) -> float:
    """Estimate size of a single transformer layer in GB."""
    if spec.param_count_b <= 0 or spec.size_bytes <= 0:
        return 0.0
    num_layers = spec.metadata.get("num_layers", 32)
    if num_layers <= 0:
        return 0.0
    return (spec.size_bytes / 1024**3) / num_layers


def _offload_overhead(
    gpu_layers: int,
    cpu_layers: int,
    param_billions: float,
) -> float:
    """Estimate transfer overhead ratio for CPU offloading.

    Overhead increases with the fraction of layers in CPU (slow PCIe transfers).
    """
    total = gpu_layers + cpu_layers
    if total == 0:
        return 0.0
    cpu_fraction = cpu_layers / total
    # Rough calibration: 50% in CPU → ~0.4 overhead ratio.
    return round(cpu_fraction * 0.8, 2)
