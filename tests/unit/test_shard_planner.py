"""Unit tests for shard_planner — all shard scenarios covered."""
from __future__ import annotations

from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from tools.gimo_server.inference.contracts import (
    DeviceCapability,
    ExecutionProviderType,
    HardwareTarget,
    MemoryBudget,
    ModelFormat,
    ModelSpec,
    QuantizationType,
    ShardStrategy,
)
from tools.gimo_server.inference.shard_planner import (
    ShardPlan,
    is_rejected,
    plan,
    _layer_size_gb,
    _offload_overhead,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _spec(size_gb: float, params_b: float = 7.0, num_layers: int = 32) -> ModelSpec:
    return ModelSpec(
        model_id=f"test-{size_gb}gb",
        path=Path(f"/fake/{size_gb}gb.onnx"),
        format=ModelFormat.ONNX,
        size_bytes=int(size_gb * 1024**3),
        param_count_b=params_b,
        quantization=QuantizationType.INT4,
        metadata={"num_layers": num_layers},
    )


def _budget(
    gpu_gb: float = 8.0,
    cpu_gb: float = 16.0,
    npu_gb: float = 0.0,
    disk_gb: float = 50.0,
) -> MemoryBudget:
    return MemoryBudget(
        gpu_available_gb=gpu_gb,
        cpu_available_gb=cpu_gb,
        npu_available_gb=npu_gb,
        disk_cache_gb=disk_gb,
        total_usable_gb=gpu_gb + cpu_gb + npu_gb + disk_gb,
        model_requires_gb=0.0,
        fits_single_device=False,
    )


def _npu_device(tops: float = 16.0) -> DeviceCapability:
    return DeviceCapability(
        device_type=HardwareTarget.NPU,
        device_name="AMD XDNA",
        total_memory_gb=24.0,
        free_memory_gb=8.0,
        compute_tops=tops,
        supports_int8=True,
        execution_providers=[ExecutionProviderType.VITIS_AI],
        is_unified_memory=True,
    )


def _gpu_device(vram_gb: float = 8.0) -> DeviceCapability:
    return DeviceCapability(
        device_type=HardwareTarget.GPU,
        device_name="RTX Test",
        total_memory_gb=vram_gb,
        free_memory_gb=vram_gb,
        execution_providers=[ExecutionProviderType.CUDA],
    )


def _cpu_device(ram_gb: float = 32.0) -> DeviceCapability:
    return DeviceCapability(
        device_type=HardwareTarget.CPU,
        device_name="Test CPU",
        total_memory_gb=ram_gb,
        free_memory_gb=ram_gb,
        execution_providers=[ExecutionProviderType.CPU],
    )


# ---------------------------------------------------------------------------
# CASE 1: Model fits entirely in GPU VRAM → NONE (no sharding)
# ---------------------------------------------------------------------------

class TestFitsInGpu:
    def test_strategy_is_none(self):
        # 4 GB model, 8 GB VRAM → fits (8 * 0.85 = 6.8 GB usable > 4 GB)
        p = plan(_spec(4.0), _budget(gpu_gb=8.0), [_gpu_device(8.0)])
        assert p.strategy == ShardStrategy.NONE
        assert not is_rejected(p)

    def test_all_layers_on_gpu(self):
        p = plan(_spec(4.0), _budget(gpu_gb=8.0), [_gpu_device(8.0)])
        assert p.layer_allocation.gpu_layers == 32
        assert p.layer_allocation.cpu_layers == 0

    def test_device_bytes_gpu_only(self):
        p = plan(_spec(4.0), _budget(gpu_gb=8.0), [_gpu_device(8.0)])
        assert "gpu" in p.device_bytes
        assert "cpu" not in p.device_bytes

    def test_no_overhead(self):
        p = plan(_spec(4.0), _budget(gpu_gb=8.0), [_gpu_device(8.0)])
        assert p.estimated_overhead_ratio == 0.0


# ---------------------------------------------------------------------------
# CASE 2: NPU + GPU split (LAYER_SPLIT)
# ---------------------------------------------------------------------------

class TestNpuGpuSplit:
    def test_layer_split_strategy(self):
        # 10 GB model, 6.8 GB usable GPU, 8 GB NPU → fits in GPU+NPU
        p = plan(
            _spec(10.0),
            _budget(gpu_gb=8.0, npu_gb=8.0, cpu_gb=0.0, disk_gb=0.0),
            [_gpu_device(8.0), _npu_device()],
        )
        assert p.strategy == ShardStrategy.LAYER_SPLIT

    def test_npu_layers_positive(self):
        p = plan(
            _spec(10.0),
            _budget(gpu_gb=8.0, npu_gb=8.0, cpu_gb=0.0, disk_gb=0.0),
            [_gpu_device(8.0), _npu_device()],
        )
        assert p.layer_allocation.npu_layers > 0

    def test_total_layers_consistent(self):
        p = plan(
            _spec(10.0),
            _budget(gpu_gb=8.0, npu_gb=8.0, cpu_gb=0.0, disk_gb=0.0),
            [_gpu_device(8.0), _npu_device()],
        )
        total = p.layer_allocation.gpu_layers + p.layer_allocation.npu_layers
        assert total == 32


# ---------------------------------------------------------------------------
# CASE 3: CPU RAM offload (OFFLOAD_CPU)
# ---------------------------------------------------------------------------

class TestCpuOffload:
    def test_offload_cpu_strategy(self):
        # 12 GB model, 6.8 GB usable GPU, 9.6 GB usable CPU → fits in GPU+CPU
        p = plan(
            _spec(12.0),
            _budget(gpu_gb=8.0, cpu_gb=16.0, npu_gb=0.0, disk_gb=0.0),
            [_gpu_device(8.0), _cpu_device(16.0)],
        )
        assert p.strategy == ShardStrategy.OFFLOAD_CPU

    def test_cpu_layers_positive(self):
        p = plan(
            _spec(12.0),
            _budget(gpu_gb=8.0, cpu_gb=16.0, npu_gb=0.0, disk_gb=0.0),
            [_gpu_device(8.0), _cpu_device(16.0)],
        )
        assert p.layer_allocation.cpu_layers > 0

    def test_overhead_positive(self):
        p = plan(
            _spec(12.0),
            _budget(gpu_gb=8.0, cpu_gb=16.0, npu_gb=0.0, disk_gb=0.0),
            [_gpu_device(8.0), _cpu_device(16.0)],
        )
        assert p.estimated_overhead_ratio > 0.0


# ---------------------------------------------------------------------------
# CASE 4: Hybrid GPU + NPU + CPU (HYBRID)
# ---------------------------------------------------------------------------

class TestHybrid:
    def test_hybrid_strategy(self):
        # 20 GB model, GPU=6.8, CPU=9.6, NPU=8 → total=24.4 > 20
        p = plan(
            _spec(20.0),
            _budget(gpu_gb=8.0, cpu_gb=16.0, npu_gb=8.0, disk_gb=0.0),
            [_gpu_device(8.0), _cpu_device(16.0), _npu_device()],
        )
        assert p.strategy == ShardStrategy.HYBRID

    def test_all_three_devices_used(self):
        p = plan(
            _spec(20.0),
            _budget(gpu_gb=8.0, cpu_gb=16.0, npu_gb=8.0, disk_gb=0.0),
            [_gpu_device(8.0), _cpu_device(16.0), _npu_device()],
        )
        alloc = p.layer_allocation
        assert alloc.gpu_layers > 0
        assert alloc.npu_layers > 0
        assert alloc.cpu_layers > 0


# ---------------------------------------------------------------------------
# CASE 5: Disk offload via mmap (OFFLOAD_DISK)
# ---------------------------------------------------------------------------

class TestDiskOffload:
    def test_disk_offload_strategy(self):
        # 60 GB model, GPU=6.8, CPU=9.6, disk=50 → total=66.4 > 60
        p = plan(
            _spec(60.0),
            _budget(gpu_gb=8.0, cpu_gb=16.0, npu_gb=0.0, disk_gb=50.0),
            [_gpu_device(8.0), _cpu_device(16.0)],
            allow_disk_offload=True,
        )
        assert p.strategy == ShardStrategy.OFFLOAD_DISK

    def test_disk_offload_disabled_causes_reject(self):
        p = plan(
            _spec(60.0),
            _budget(gpu_gb=8.0, cpu_gb=16.0, npu_gb=0.0, disk_gb=0.0),
            [_gpu_device(8.0), _cpu_device(16.0)],
            allow_disk_offload=False,
        )
        assert is_rejected(p)

    def test_disk_layers_positive(self):
        p = plan(
            _spec(60.0),
            _budget(gpu_gb=8.0, cpu_gb=16.0, npu_gb=0.0, disk_gb=50.0),
            [_gpu_device(8.0), _cpu_device(16.0)],
        )
        assert p.layer_allocation.disk_layers > 0

    def test_high_overhead_ratio(self):
        p = plan(
            _spec(60.0),
            _budget(gpu_gb=8.0, cpu_gb=16.0, npu_gb=0.0, disk_gb=50.0),
            [_gpu_device(8.0), _cpu_device(16.0)],
        )
        assert p.estimated_overhead_ratio >= 0.5


# ---------------------------------------------------------------------------
# CASE 6: REJECT
# ---------------------------------------------------------------------------

class TestReject:
    def test_reject_when_too_large(self):
        # 500 GB model, total usable = 100 GB → way over max_oversized_ratio
        p = plan(
            _spec(500.0),
            _budget(gpu_gb=8.0, cpu_gb=16.0, disk_gb=50.0),
            [_gpu_device(8.0), _cpu_device(16.0)],
            max_oversized_ratio=3.0,
        )
        assert is_rejected(p)
        assert p.reject_reason

    def test_reject_reason_contains_model_size(self):
        p = plan(
            _spec(500.0),
            _budget(gpu_gb=8.0, cpu_gb=16.0, disk_gb=50.0),
            [_gpu_device(8.0)],
            max_oversized_ratio=3.0,
        )
        assert "500" in p.reject_reason or "GB" in p.reject_reason


# ---------------------------------------------------------------------------
# ROG Ally X scenario (24 GB unified, 16 TOPS NPU)
# ---------------------------------------------------------------------------

class TestRogAllyX:
    def test_13b_q4_fits_without_sharding(self):
        """13B Q4 (~8 GB) fits in 24 GB unified pool → NONE."""
        p = plan(
            _spec(8.0, params_b=13.0),
            _budget(gpu_gb=20.0, cpu_gb=20.0, npu_gb=7.0, disk_gb=50.0),
            [_gpu_device(20.0), _cpu_device(20.0), _npu_device(16.0)],
        )
        assert p.strategy == ShardStrategy.NONE

    def test_70b_q4_needs_disk_offload(self):
        """70B Q4 (~40 GB) needs disk offload on 24 GB unified pool."""
        p = plan(
            _spec(40.0, params_b=70.0),
            _budget(gpu_gb=18.0, cpu_gb=18.0, npu_gb=7.0, disk_gb=50.0),
            [_gpu_device(18.0), _cpu_device(18.0), _npu_device(16.0)],
        )
        assert p.strategy in (ShardStrategy.OFFLOAD_DISK, ShardStrategy.HYBRID)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_layer_size_gb(self):
        spec = _spec(32.0)
        size = _layer_size_gb(spec)
        assert abs(size - 1.0) < 0.01   # 32 GB / 32 layers = 1.0 GB

    def test_layer_size_zero_params(self):
        spec = _spec(0.0)
        assert _layer_size_gb(spec) == 0.0

    def test_offload_overhead_all_cpu(self):
        ratio = _offload_overhead(0, 32, 7.0)
        assert ratio == pytest.approx(0.8)

    def test_offload_overhead_half_cpu(self):
        ratio = _offload_overhead(16, 16, 7.0)
        assert ratio == pytest.approx(0.4)

    def test_offload_overhead_no_cpu(self):
        assert _offload_overhead(32, 0, 7.0) == 0.0
