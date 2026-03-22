"""Memory Manager — budget calculation and shard execution coordination.

Orchestrates the three-step flow:
  1. calculate_budget()  — how much memory is available on each device
  2. plan_sharding()     — which ShardStrategy and LayerAllocation to use
  3. ensure_loaded()     — load/shard the model if not already in the pool

This is the primary entry point for the engine when it needs a model loaded.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import psutil

from .contracts import (
    DeviceCapability,
    HardwareTarget,
    MemoryBudget,
    ModelSpec,
)
from .shard_planner import ShardPlan, plan as plan_shards, is_rejected

logger = logging.getLogger("gie.memory_manager")

# Disk cache quota for disk-offload scenarios (50 GB default).
DEFAULT_DISK_CACHE_GB = 50.0


class MemoryManager:
    """Calculates budgets and orchestrates model loading/sharding."""

    def __init__(
        self,
        *,
        disk_cache_dir: Optional[Path] = None,
        disk_cache_gb: float = DEFAULT_DISK_CACHE_GB,
        max_oversized_ratio: float = 3.0,
    ) -> None:
        self._disk_cache_dir = disk_cache_dir or Path.home() / ".gimo" / "models"
        self._disk_cache_gb = disk_cache_gb
        self._max_oversized_ratio = max_oversized_ratio

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_budget(
        self,
        model: ModelSpec,
        devices: List[DeviceCapability],
    ) -> MemoryBudget:
        """Calculate available memory budget across all devices.

        Args:
            model:   The model that will be loaded.
            devices: Detected devices from DeviceDetector.

        Returns:
            A :class:`MemoryBudget` populated with free memory per device.
        """
        gpu_gb = 0.0
        cpu_gb = 0.0
        npu_gb = 0.0

        for dev in devices:
            if dev.device_type == HardwareTarget.GPU:
                gpu_gb = max(gpu_gb, dev.free_memory_gb)
            elif dev.device_type == HardwareTarget.CPU:
                cpu_gb = dev.free_memory_gb
            elif dev.device_type == HardwareTarget.NPU:
                npu_gb = max(npu_gb, dev.free_memory_gb)

        # APU: if unified memory, GPU and CPU share the same pool.
        # Avoid double-counting by capping GPU to what CPU reports as free.
        is_unified = any(d.is_unified_memory for d in devices)
        if is_unified:
            # On APU, free_memory_gb for GPU is the same LPDDR pool.
            # We use CPU's view as the authoritative figure.
            gpu_gb = min(gpu_gb, cpu_gb)

        disk_gb = self._available_disk_cache_gb()

        model_gb = model.size_bytes / 1024**3
        total_usable = gpu_gb + cpu_gb + npu_gb + disk_gb

        fits_single = model_gb <= gpu_gb * (1 - 0.15)  # 15% VRAM margin

        # Pre-compute recommended shard strategy for quick access.
        budget = MemoryBudget(
            gpu_available_gb=round(gpu_gb, 3),
            cpu_available_gb=round(cpu_gb, 3),
            npu_available_gb=round(npu_gb, 3),
            disk_cache_gb=round(disk_gb, 3),
            total_usable_gb=round(total_usable, 3),
            model_requires_gb=round(model_gb, 3),
            fits_single_device=fits_single,
        )
        return budget

    def plan_sharding(
        self,
        budget: MemoryBudget,
        model: ModelSpec,
        devices: List[DeviceCapability],
    ) -> ShardPlan:
        """Determine the best shard strategy given the budget."""
        shard_plan = plan_shards(
            spec=model,
            budget=budget,
            devices=devices,
            allow_disk_offload=True,
            max_oversized_ratio=self._max_oversized_ratio,
        )
        if is_rejected(shard_plan):
            logger.warning(
                "Model %s rejected: %s",
                model.model_id,
                shard_plan.reject_reason,
            )
        else:
            logger.info(
                "Shard plan for %s: strategy=%s, rationale=%s",
                model.model_id,
                shard_plan.strategy.value,
                shard_plan.rationale,
            )
        # Store recommended strategy in the budget for upstream callers.
        budget.recommended_shard = shard_plan.strategy
        budget.shard_plan = {
            k: round(v / 1024**3, 3) for k, v in shard_plan.device_bytes.items()
        }
        return shard_plan

    def fits_in_memory(self, model: ModelSpec, devices: List[DeviceCapability]) -> bool:
        """Quick check: can the model be loaded at all (including disk offload)?"""
        budget = self.calculate_budget(model, devices)
        shard = plan_shards(
            spec=model,
            budget=budget,
            devices=devices,
            allow_disk_offload=True,
            max_oversized_ratio=self._max_oversized_ratio,
        )
        return not is_rejected(shard)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _available_disk_cache_gb(self) -> float:
        """Return usable disk space (capped by configured quota)."""
        try:
            self._disk_cache_dir.mkdir(parents=True, exist_ok=True)
            usage = psutil.disk_usage(str(self._disk_cache_dir))
            free_gb = usage.free / 1024**3
            return min(free_gb, self._disk_cache_gb)
        except Exception as exc:
            logger.warning("Cannot check disk space: %s", exc)
            return 0.0
