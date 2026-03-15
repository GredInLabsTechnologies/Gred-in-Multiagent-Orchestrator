"""Unit tests for device_detector — mocks subprocess/psutil."""
from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Provide psutil stub
# ---------------------------------------------------------------------------

def _make_psutil_stub() -> types.ModuleType:
    ps = types.ModuleType("psutil")

    class _VirtualMemory:
        total = 32 * 1024**3      # 32 GB
        available = 20 * 1024**3  # 20 GB free
        percent = 37.5

    ps.virtual_memory = lambda: _VirtualMemory()
    ps.cpu_count = lambda logical=True: 8 if logical else 4
    return ps


if "psutil" not in sys.modules:
    sys.modules["psutil"] = _make_psutil_stub()


from tools.gimo_server.inference.contracts import (
    ExecutionProviderType,
    HardwareTarget,
)
from tools.gimo_server.inference.hardware.device_detector import (
    _npu_from_cpu_name,
    _estimate_cpu_bandwidth,
    get_devices,
)
from tools.gimo_server.inference.hardware.cpu_backend import estimate_tps
from tools.gimo_server.inference.hardware.gpu_backend import estimate_tps as gpu_tps, vram_required_gb
from tools.gimo_server.inference.hardware.npu_backend import npu_can_handle, npu_layers_for_embedding_attention
from tools.gimo_server.inference.hardware.unified_memory_manager import (
    adjust_for_memory_pressure,
    plan_unified_memory,
    rog_ally_x_plan,
    UnifiedMemoryPlan,
)
from tools.gimo_server.inference.contracts import DeviceCapability


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def cpu_device() -> DeviceCapability:
    return DeviceCapability(
        device_type=HardwareTarget.CPU,
        device_name="Test CPU",
        total_memory_gb=32.0,
        free_memory_gb=20.0,
        memory_bandwidth_gbps=48.0,
        supports_int8=True,
    )


@pytest.fixture()
def gpu_device() -> DeviceCapability:
    return DeviceCapability(
        device_type=HardwareTarget.GPU,
        device_name="NVIDIA RTX 4090",
        total_memory_gb=24.0,
        free_memory_gb=20.0,
        compute_tops=165.0,
        memory_bandwidth_gbps=1008.0,
        supports_int8=True,
        supports_bf16=True,
        supports_int4=True,
        execution_providers=[ExecutionProviderType.CUDA, ExecutionProviderType.CPU],
    )


@pytest.fixture()
def npu_device() -> DeviceCapability:
    return DeviceCapability(
        device_type=HardwareTarget.NPU,
        device_name="AMD XDNA (Z1 Extreme / Phoenix)",
        total_memory_gb=24.0,
        free_memory_gb=7.0,
        compute_tops=16.0,
        memory_bandwidth_gbps=102.0,
        supports_int8=True,
        supports_int4=False,
        execution_providers=[ExecutionProviderType.VITIS_AI, ExecutionProviderType.CPU],
        is_unified_memory=True,
    )


# ---------------------------------------------------------------------------
# Tests — device_detector helpers
# ---------------------------------------------------------------------------

class TestEstimateCpuBandwidth:
    def test_returns_positive_float(self):
        bw = _estimate_cpu_bandwidth()
        assert isinstance(bw, float)
        assert bw > 0


class TestNpuFromCpuName:
    def test_amd_z1_extreme_detected(self):
        device = _npu_from_cpu_name("amd ryzen z1 extreme")
        assert device is not None
        assert device.device_type == HardwareTarget.NPU
        assert device.compute_tops == 16.0
        assert device.is_unified_memory is True

    def test_amd_strix_halo_high_tops(self):
        device = _npu_from_cpu_name("amd ryzen ai strix halo")
        assert device is not None
        assert device.compute_tops == 50.0

    def test_intel_core_ultra_detected(self):
        device = _npu_from_cpu_name("intel core ultra 165h meteor lake")
        assert device is not None
        assert device.device_type == HardwareTarget.NPU
        assert "Intel NPU" in device.device_name

    def test_intel_lunar_lake_higher_tops(self):
        device = _npu_from_cpu_name("intel core ultra 258v lunar lake")
        assert device is not None
        assert device.compute_tops == 48.0

    def test_unknown_cpu_returns_none(self):
        device = _npu_from_cpu_name("generic x86 cpu no npu")
        assert device is None


class TestGetDevices:
    def test_always_returns_at_least_cpu(self):
        # Mock subprocess to avoid real hardware calls.
        with patch("tools.gimo_server.inference.hardware.device_detector.subprocess") as mock_sub:
            mock_sub.run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            with patch("tools.gimo_server.inference.hardware.device_detector._try_nvidia", return_value=None):
                with patch("tools.gimo_server.inference.hardware.device_detector._try_amd_or_intel_gpu", return_value=None):
                    devices = get_devices(force_refresh=True)
        assert len(devices) >= 1
        assert any(d.device_type == HardwareTarget.CPU for d in devices)

    def test_cache_returns_same_result(self):
        with patch("tools.gimo_server.inference.hardware.device_detector._try_nvidia", return_value=None):
            with patch("tools.gimo_server.inference.hardware.device_detector._try_amd_or_intel_gpu", return_value=None):
                d1 = get_devices(force_refresh=True)
                d2 = get_devices(force_refresh=False)   # should return cached
        assert d1 is d2


# ---------------------------------------------------------------------------
# Tests — cpu_backend.estimate_tps
# ---------------------------------------------------------------------------

class TestCpuEstimateTps:
    def test_basic_formula(self):
        tps = estimate_tps(7.0, 8)
        expected = (8 * 2.5) / 7.0
        assert abs(tps - expected) < 0.01

    def test_zero_params_returns_zero(self):
        assert estimate_tps(0.0, 8) == 0.0

    def test_more_cores_better(self):
        assert estimate_tps(7.0, 16) > estimate_tps(7.0, 4)


# ---------------------------------------------------------------------------
# Tests — gpu_backend
# ---------------------------------------------------------------------------

class TestGpuEstimateTps:
    def test_formula(self):
        # bw=1008, params=7B, bytes=2 (FP16): tps = (1008 * 0.5) / (7 * 2) = 36
        tps = gpu_tps(1008.0, 7.0, bytes_per_param=2.0)
        assert abs(tps - 36.0) < 1.0

    def test_higher_bandwidth_better(self):
        assert gpu_tps(1000.0, 7.0) > gpu_tps(400.0, 7.0)

    def test_more_params_slower(self):
        assert gpu_tps(1000.0, 70.0) < gpu_tps(1000.0, 7.0)


class TestVramRequired:
    def test_fp16_7b(self):
        gb = vram_required_gb(7.0, bytes_per_param=2.0)
        # 7 * 2 * 1.2 = 16.8 GB
        assert abs(gb - 16.8) < 0.1

    def test_int4_7b(self):
        gb = vram_required_gb(7.0, bytes_per_param=0.5)
        # 7 * 0.5 * 1.2 = 4.2 GB
        assert abs(gb - 4.2) < 0.1


# ---------------------------------------------------------------------------
# Tests — npu_backend
# ---------------------------------------------------------------------------

class TestNpuCanHandle:
    def test_small_model_npu_only(self, npu_device):
        assert npu_can_handle(npu_device, 1.5) is True

    def test_large_model_rejected_solo(self, npu_device):
        assert npu_can_handle(npu_device, 7.0) is False

    def test_medium_model_hybrid(self, npu_device):
        assert npu_can_handle(npu_device, 7.0, hybrid=True) is True

    def test_too_large_even_hybrid(self, npu_device):
        assert npu_can_handle(npu_device, 20.0, hybrid=True) is False

    def test_cpu_device_returns_false(self, cpu_device):
        assert npu_can_handle(cpu_device, 1.0) is False


class TestNpuLayersForEmbeddingAttention:
    def test_returns_nonzero_for_npu(self, npu_device):
        layers = npu_layers_for_embedding_attention(32, npu_device)
        assert layers >= 1

    def test_returns_zero_for_cpu(self, cpu_device):
        layers = npu_layers_for_embedding_attention(32, cpu_device)
        assert layers == 0

    def test_25_percent_heuristic(self, npu_device):
        layers = npu_layers_for_embedding_attention(40, npu_device)
        assert layers == 10


# ---------------------------------------------------------------------------
# Tests — unified_memory_manager
# ---------------------------------------------------------------------------

class TestPlanUnifiedMemory:
    def test_no_unified_device_returns_none(self, cpu_device):
        assert plan_unified_memory([cpu_device]) is None

    def test_unified_device_returns_plan(self, npu_device):
        plan = plan_unified_memory([npu_device])
        assert plan is not None
        assert plan.zero_copy_available is True
        assert plan.model_weights_gb > 0

    def test_weights_plus_kv_plus_overhead_equals_total(self, npu_device):
        plan = plan_unified_memory([npu_device], system_reserve_gb=4.0)
        total_accounted = (
            plan.system_reserved_gb + plan.model_weights_gb + plan.kv_cache_gb
        )
        # Allow 0.5 GB rounding tolerance.
        assert abs(total_accounted - plan.total_pool_gb) < 0.5


class TestAdjustForPressure:
    def test_no_pressure_unchanged(self):
        plan = rog_ally_x_plan()
        # Need free >= system_reserved + model_weights = 5.5 + 17.0 = 22.5 GB
        adjusted = adjust_for_memory_pressure(plan, current_free_gb=23.0)
        assert adjusted.model_weights_gb == plan.model_weights_gb

    def test_high_pressure_reduces_budget(self):
        plan = rog_ally_x_plan()
        adjusted = adjust_for_memory_pressure(plan, current_free_gb=6.0)
        assert adjusted.model_weights_gb < plan.model_weights_gb

    def test_rog_ally_x_plan_sensible(self):
        plan = rog_ally_x_plan()
        assert plan.total_pool_gb == 24.0
        assert plan.zero_copy_available is True
        assert plan.model_weights_gb > 10.0   # plenty for a 13B Q4 model
