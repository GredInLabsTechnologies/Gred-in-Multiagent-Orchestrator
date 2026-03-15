"""Unit tests for MemoryManager budget calculations."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# psutil stub (already registered in test_device_detector but we need it here too)
def _make_psutil_stub() -> types.ModuleType:
    ps = types.ModuleType("psutil")

    class _VirtMem:
        total = 32 * 1024**3
        available = 20 * 1024**3
        percent = 37.5

    class _DiskUsage:
        free = 100 * 1024**3  # 100 GB free disk

    ps.virtual_memory = lambda: _VirtMem()
    ps.cpu_count = lambda logical=True: 8 if logical else 4
    ps.disk_usage = lambda _: _DiskUsage()
    return ps


if "psutil" not in sys.modules:
    sys.modules["psutil"] = _make_psutil_stub()
else:
    # Patch disk_usage into existing stub.
    class _DiskUsage:
        free = 100 * 1024**3
    sys.modules["psutil"].disk_usage = lambda _: _DiskUsage()


from tools.gimo_server.inference.contracts import (
    DeviceCapability,
    ExecutionProviderType,
    HardwareTarget,
    ModelFormat,
    ModelSpec,
    QuantizationType,
    ShardStrategy,
)
from tools.gimo_server.inference.memory_manager import MemoryManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _spec(size_gb: float, params_b: float = 7.0) -> ModelSpec:
    return ModelSpec(
        model_id=f"test-{size_gb}gb",
        path=Path(f"/fake/{size_gb}gb.onnx"),
        format=ModelFormat.ONNX,
        size_bytes=int(size_gb * 1024**3),
        param_count_b=params_b,
        quantization=QuantizationType.INT4,
        metadata={"num_layers": 32},
    )


def _gpu_dev(vram_gb: float) -> DeviceCapability:
    return DeviceCapability(
        device_type=HardwareTarget.GPU,
        device_name="Test GPU",
        total_memory_gb=vram_gb,
        free_memory_gb=vram_gb,
        execution_providers=[ExecutionProviderType.CUDA],
    )


def _cpu_dev(ram_gb: float) -> DeviceCapability:
    return DeviceCapability(
        device_type=HardwareTarget.CPU,
        device_name="Test CPU",
        total_memory_gb=ram_gb,
        free_memory_gb=ram_gb,
        execution_providers=[ExecutionProviderType.CPU],
    )


@pytest.fixture()
def manager(tmp_path: Path) -> MemoryManager:
    return MemoryManager(disk_cache_dir=tmp_path, disk_cache_gb=50.0)


# ---------------------------------------------------------------------------
# Tests — calculate_budget
# ---------------------------------------------------------------------------

class TestCalculateBudget:
    def test_gpu_free_reported(self, manager):
        devices = [_gpu_dev(8.0), _cpu_dev(32.0)]
        budget = manager.calculate_budget(_spec(4.0), devices)
        assert budget.gpu_available_gb == pytest.approx(8.0, abs=0.01)

    def test_cpu_free_reported(self, manager):
        devices = [_gpu_dev(8.0), _cpu_dev(32.0)]
        budget = manager.calculate_budget(_spec(4.0), devices)
        assert budget.cpu_available_gb == pytest.approx(32.0, abs=0.01)

    def test_disk_included(self, manager):
        devices = [_cpu_dev(16.0)]
        budget = manager.calculate_budget(_spec(4.0), devices)
        # disk_cache_gb is capped at 50.0 (the constructor arg)
        assert budget.disk_cache_gb == pytest.approx(50.0, abs=1.0)

    def test_model_size_recorded(self, manager):
        devices = [_gpu_dev(8.0)]
        budget = manager.calculate_budget(_spec(4.0), devices)
        assert budget.model_requires_gb == pytest.approx(4.0, abs=0.01)

    def test_fits_single_device_true_for_small_model(self, manager):
        devices = [_gpu_dev(24.0)]
        budget = manager.calculate_budget(_spec(4.0), devices)
        assert budget.fits_single_device is True

    def test_fits_single_device_false_for_large_model(self, manager):
        devices = [_gpu_dev(8.0)]
        budget = manager.calculate_budget(_spec(12.0), devices)
        assert budget.fits_single_device is False

    def test_unified_memory_caps_gpu(self, manager):
        """On APU, GPU and CPU share the same pool — don't double-count."""
        apu = DeviceCapability(
            device_type=HardwareTarget.GPU,
            device_name="APU GPU",
            total_memory_gb=24.0,
            free_memory_gb=20.0,
            is_unified_memory=True,
            execution_providers=[ExecutionProviderType.DIRECTML],
        )
        cpu = DeviceCapability(
            device_type=HardwareTarget.CPU,
            device_name="APU CPU",
            total_memory_gb=24.0,
            free_memory_gb=18.0,  # slightly less free
            is_unified_memory=True,
            execution_providers=[ExecutionProviderType.CPU],
        )
        budget = manager.calculate_budget(_spec(4.0), [apu, cpu])
        # GPU free must be capped at CPU free (they share memory)
        assert budget.gpu_available_gb <= budget.cpu_available_gb


# ---------------------------------------------------------------------------
# Tests — plan_sharding
# ---------------------------------------------------------------------------

class TestPlanSharding:
    def test_small_model_no_sharding(self, manager):
        devices = [_gpu_dev(8.0), _cpu_dev(32.0)]
        spec = _spec(4.0)
        budget = manager.calculate_budget(spec, devices)
        shard = manager.plan_sharding(budget, spec, devices)
        assert shard.strategy == ShardStrategy.NONE

    def test_oversized_model_uses_cpu_offload(self, manager):
        devices = [_gpu_dev(8.0), _cpu_dev(32.0)]
        spec = _spec(12.0)
        budget = manager.calculate_budget(spec, devices)
        shard = manager.plan_sharding(budget, spec, devices)
        assert shard.strategy in (
            ShardStrategy.OFFLOAD_CPU,
            ShardStrategy.HYBRID,
            ShardStrategy.OFFLOAD_DISK,
        )

    def test_budget_recommended_shard_updated(self, manager):
        devices = [_gpu_dev(8.0), _cpu_dev(32.0)]
        spec = _spec(12.0)
        budget = manager.calculate_budget(spec, devices)
        manager.plan_sharding(budget, spec, devices)
        assert budget.recommended_shard != ShardStrategy.NONE

    def test_budget_shard_plan_dict_populated(self, manager):
        devices = [_gpu_dev(8.0), _cpu_dev(32.0)]
        spec = _spec(12.0)
        budget = manager.calculate_budget(spec, devices)
        manager.plan_sharding(budget, spec, devices)
        assert len(budget.shard_plan) > 0


# ---------------------------------------------------------------------------
# Tests — fits_in_memory
# ---------------------------------------------------------------------------

class TestFitsInMemory:
    def test_small_model_fits(self, manager):
        assert manager.fits_in_memory(_spec(4.0), [_gpu_dev(8.0)])

    def test_huge_model_does_not_fit(self, manager):
        # Manager has disk cap of 50 GB; with max_oversized_ratio=3.0:
        # total = 8 + 32 + 50 = 90 GB usable; 3 * 90 = 270 GB threshold.
        # Model of 300 GB > threshold → reject.
        assert not manager.fits_in_memory(
            _spec(300.0, 600.0),
            [_gpu_dev(8.0), _cpu_dev(32.0)],
        )
