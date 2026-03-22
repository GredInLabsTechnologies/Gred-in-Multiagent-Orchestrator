"""Unified memory management for APU/SoC platforms.

On devices like ROG Ally X (AMD Z1 Extreme), Steam Deck, or Apple M-series,
the GPU and CPU share a single high-bandwidth LPDDR pool.  This module
computes an optimal memory split and enables zero-copy tensor access.

Key insight: because there is no PCIe bus between CPU and GPU memory, we can
map model weights once and reference them from both processing units without
copying — dramatically reducing memory overhead versus discrete GPU setups.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import psutil

from ..contracts import DeviceCapability

logger = logging.getLogger("gie.hardware.unified_memory")


@dataclass
class UnifiedMemoryPlan:
    """Memory allocation plan for a unified-memory APU."""
    total_pool_gb: float
    system_reserved_gb: float       # OS + background processes
    gpu_context_gb: float           # GPU driver / rendering context
    npu_context_gb: float           # NPU firmware + buffers
    model_weights_gb: float         # available for model weights
    kv_cache_gb: float              # remaining for KV cache
    zero_copy_available: bool       # True → no host↔device copies needed
    recommended_max_model_gb: float # practical cap for good UX


def plan_unified_memory(
    devices: List[DeviceCapability],
    *,
    system_reserve_gb: float = 4.0,   # keep 4 GB for OS
    gpu_context_gb: float = 1.0,      # GPU driver overhead
    npu_context_gb: float = 0.5,      # NPU firmware
) -> Optional[UnifiedMemoryPlan]:
    """Compute a unified-memory plan if the platform supports it.

    Returns None if no unified-memory device is detected.
    """
    # Find a unified-memory device (APU).
    unified_device = next(
        (d for d in devices if d.is_unified_memory),
        None,
    )
    if unified_device is None:
        return None

    mem = psutil.virtual_memory()
    total_gb = mem.total / 1024**3

    # On unified-memory APUs the reported total RAM *is* the shared pool.
    # We deduct OS + GPU context + NPU context to find usable model memory.
    overhead_gb = system_reserve_gb + gpu_context_gb + npu_context_gb
    model_gb = max(0.0, total_gb - overhead_gb)

    # Allocate ~15% of model budget to KV cache (conversation history).
    kv_fraction = 0.15
    kv_gb = model_gb * kv_fraction
    weights_gb = model_gb - kv_gb

    # Zero-copy is available on all APU platforms we target.
    zero_copy = True

    # Recommended practical cap: leave 10% headroom to avoid OOM thrash.
    recommended = weights_gb * 0.9

    logger.info(
        "Unified memory plan: total=%.1f GB, model=%.1f GB, kv=%.1f GB, zero_copy=%s",
        total_gb,
        weights_gb,
        kv_gb,
        zero_copy,
    )

    return UnifiedMemoryPlan(
        total_pool_gb=round(total_gb, 2),
        system_reserved_gb=round(overhead_gb, 2),
        gpu_context_gb=gpu_context_gb,
        npu_context_gb=npu_context_gb,
        model_weights_gb=round(weights_gb, 2),
        kv_cache_gb=round(kv_gb, 2),
        zero_copy_available=zero_copy,
        recommended_max_model_gb=round(recommended, 2),
    )


def adjust_for_memory_pressure(
    plan: UnifiedMemoryPlan,
    current_free_gb: float,
) -> UnifiedMemoryPlan:
    """Dynamically shrink the model budget if memory is under pressure.

    Called periodically by the scheduler to adapt to changing system load
    (e.g., a browser opening with many tabs).
    """
    headroom_gb = current_free_gb - plan.system_reserved_gb
    if headroom_gb < plan.model_weights_gb:
        # Shrink model budget to what is actually available.
        new_weights = max(0.0, headroom_gb - plan.kv_cache_gb)
        logger.warning(
            "Memory pressure: reducing model budget from %.1f to %.1f GB",
            plan.model_weights_gb,
            new_weights,
        )
        return UnifiedMemoryPlan(
            total_pool_gb=plan.total_pool_gb,
            system_reserved_gb=plan.system_reserved_gb,
            gpu_context_gb=plan.gpu_context_gb,
            npu_context_gb=plan.npu_context_gb,
            model_weights_gb=round(new_weights, 2),
            kv_cache_gb=plan.kv_cache_gb,
            zero_copy_available=plan.zero_copy_available,
            recommended_max_model_gb=round(new_weights * 0.9, 2),
        )
    return plan


def rog_ally_x_plan() -> UnifiedMemoryPlan:
    """Pre-computed plan for the ROG Ally X (24 GB LPDDR5X, Z1 Extreme NPU).

    Used as a reference and in tests.
    """
    return UnifiedMemoryPlan(
        total_pool_gb=24.0,
        system_reserved_gb=5.5,     # 4 GB OS + 1 GB GPU ctx + 0.5 GB NPU
        gpu_context_gb=1.0,
        npu_context_gb=0.5,
        model_weights_gb=17.0,       # 24 - 5.5 - 2.55 (kv)
        kv_cache_gb=2.55,
        zero_copy_available=True,
        recommended_max_model_gb=15.3,
    )
