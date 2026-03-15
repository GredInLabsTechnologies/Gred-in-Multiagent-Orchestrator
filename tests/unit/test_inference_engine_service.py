"""Unit tests for InferenceEngineService and InferenceMetrics."""
from __future__ import annotations

import asyncio
import sys
import time
import types
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# psutil stub (re-use if already registered)
# ---------------------------------------------------------------------------
def _make_psutil_stub() -> types.ModuleType:
    ps = types.ModuleType("psutil")

    class _VirtMem:
        total = 32 * 1024**3
        available = 20 * 1024**3
        percent = 37.5

    class _DiskUsage:
        free = 100 * 1024**3

    ps.virtual_memory = lambda: _VirtMem()
    ps.cpu_count = lambda logical=True: 8 if logical else 4
    ps.disk_usage = lambda _: _DiskUsage()
    return ps


if "psutil" not in sys.modules:
    sys.modules["psutil"] = _make_psutil_stub()
else:
    class _DiskUsage:
        free = 100 * 1024**3
    sys.modules["psutil"].disk_usage = lambda _: _DiskUsage()


from tools.gimo_server.inference.contracts import (
    DeviceCapability,
    ExecutionProviderType,
    HardwareTarget,
    InferenceRequest,
    ModelFormat,
    ModelSpec,
    TaskSemantic,
    QuantizationType,
)
from tools.gimo_server.inference.metrics import InferenceMetrics
from tools.gimo_server.inference.engine_service import InferenceEngineService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _request(
    task: TaskSemantic = TaskSemantic.GENERAL,
    model_id: str = "test-model",
) -> InferenceRequest:
    return InferenceRequest(
        request_id=str(uuid.uuid4()),
        model_id=model_id,
        task=task,
        inputs={"prompt": "hello"},
        target_hardware=HardwareTarget.AUTO,
    )


def _cpu_device() -> DeviceCapability:
    return DeviceCapability(
        device_type=HardwareTarget.CPU,
        device_name="Test CPU",
        total_memory_gb=32.0,
        free_memory_gb=20.0,
        execution_providers=[ExecutionProviderType.CPU],
    )


# ---------------------------------------------------------------------------
# InferenceMetrics tests
# ---------------------------------------------------------------------------

class TestInferenceMetrics:
    def test_initial_state_zero(self):
        m = InferenceMetrics()
        assert m._total_requests == 0
        assert m._total_errors == 0

    def test_record_request_increments_counter(self):
        m = InferenceMetrics()
        m.record_request("r1", "model", "general", "cpu", 100.0)
        assert m._total_requests == 1

    def test_record_error_increments_error_counter(self):
        m = InferenceMetrics()
        m.record_request("r1", "model", "general", "cpu", 100.0, error="boom")
        assert m._total_errors == 1

    def test_to_dict_structure(self):
        m = InferenceMetrics()
        m.record_request("r1", "model", "general", "gpu", 50.0, tokens_generated=100, tokens_per_second=20.0)
        d = m.to_dict()
        assert "total_requests" in d
        assert "device_stats" in d
        assert "task_stats" in d
        assert "session_pool" in d

    def test_device_stats_aggregation(self):
        m = InferenceMetrics()
        m.record_request("r1", "m1", "general", "gpu", 100.0)
        m.record_request("r2", "m1", "general", "gpu", 200.0)
        d = m.to_dict()
        assert d["device_stats"]["gpu"]["requests"] == 2
        assert d["device_stats"]["gpu"]["avg_latency_ms"] == pytest.approx(150.0)

    def test_task_stats_aggregation(self):
        m = InferenceMetrics()
        m.record_request("r1", "m1", "embedding", "npu", 50.0)
        m.record_request("r2", "m1", "embedding", "npu", 150.0)
        d = m.to_dict()
        assert d["task_stats"]["embedding"]["requests"] == 2
        assert d["task_stats"]["embedding"]["avg_latency_ms"] == pytest.approx(100.0)

    def test_pool_stats_update(self):
        m = InferenceMetrics()
        m.update_pool_stats(hits=10, misses=2, evictions=1)
        d = m.to_dict()
        assert d["session_pool"]["hits"] == 10
        assert d["session_pool"]["misses"] == 2
        assert d["session_pool"]["hit_rate"] == pytest.approx(10 / 12, abs=0.01)

    def test_hit_rate_zero_when_no_requests(self):
        m = InferenceMetrics()
        d = m.to_dict()
        assert d["session_pool"]["hit_rate"] == 0.0

    def test_model_load_time_avg(self):
        m = InferenceMetrics()
        m.record_model_load(100.0)
        m.record_model_load(200.0)
        d = m.to_dict()
        assert d["model_load_avg_ms"] == pytest.approx(150.0)

    def test_error_rate(self):
        m = InferenceMetrics()
        m.record_request("r1", "m", "g", "cpu", 10.0)
        m.record_request("r2", "m", "g", "cpu", 10.0, error="fail")
        d = m.to_dict()
        assert d["error_rate"] == pytest.approx(0.5)

    def test_queue_snapshot(self):
        m = InferenceMetrics()
        m.update_queue_snapshot({"gpu": 3, "cpu": 0})
        d = m.to_dict()
        assert d["queue_depths"]["gpu"] == 3


# ---------------------------------------------------------------------------
# InferenceEngineService tests
# ---------------------------------------------------------------------------

class TestInferenceEngineServiceInit:
    def setup_method(self):
        InferenceEngineService.reset_instance()

    def test_get_instance_returns_singleton(self):
        a = InferenceEngineService.get_instance()
        b = InferenceEngineService.get_instance()
        assert a is b

    def test_reset_instance_creates_new(self):
        a = InferenceEngineService.get_instance()
        InferenceEngineService.reset_instance()
        b = InferenceEngineService.get_instance()
        assert a is not b

    @pytest.mark.asyncio
    async def test_initialize_sets_flag(self):
        with patch(
            "tools.gimo_server.inference.engine_service.get_devices",
            return_value=[_cpu_device()],
        ):
            engine = InferenceEngineService()
            await engine.initialize()
            assert engine._initialized is True
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_double_initialize_is_idempotent(self):
        with patch(
            "tools.gimo_server.inference.engine_service.get_devices",
            return_value=[_cpu_device()],
        ):
            engine = InferenceEngineService()
            await engine.initialize()
            await engine.initialize()  # should not raise or duplicate
            assert engine._initialized is True
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_resets_flag(self):
        with patch(
            "tools.gimo_server.inference.engine_service.get_devices",
            return_value=[_cpu_device()],
        ):
            engine = InferenceEngineService()
            await engine.initialize()
            await engine.shutdown()
            assert engine._initialized is False


class TestInferenceEngineServiceStatus:
    @pytest.mark.asyncio
    async def test_get_status_not_initialized(self):
        InferenceEngineService.reset_instance()
        engine = InferenceEngineService()
        status = engine.get_status()
        assert status["initialized"] is False

    @pytest.mark.asyncio
    async def test_get_status_initialized(self):
        with patch(
            "tools.gimo_server.inference.engine_service.get_devices",
            return_value=[_cpu_device()],
        ):
            engine = InferenceEngineService()
            await engine.initialize()
            status = engine.get_status()
            assert status["initialized"] is True
            assert len(status["devices"]) == 1
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_get_device_status(self):
        with patch(
            "tools.gimo_server.inference.engine_service.get_devices",
            return_value=[_cpu_device()],
        ):
            engine = InferenceEngineService()
            await engine.initialize()
            devices = engine.get_device_status()
            assert len(devices) == 1
            assert devices[0].device_type == HardwareTarget.CPU
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_get_metrics_returns_dict(self):
        with patch(
            "tools.gimo_server.inference.engine_service.get_devices",
            return_value=[_cpu_device()],
        ):
            engine = InferenceEngineService()
            await engine.initialize()
            metrics = engine.get_metrics()
            assert "total_requests" in metrics
            assert "device_stats" in metrics
            await engine.shutdown()


class TestInferenceEngineServiceModelManagement:
    @pytest.mark.asyncio
    async def test_unload_nonexistent_model_safe(self):
        with patch(
            "tools.gimo_server.inference.engine_service.get_devices",
            return_value=[_cpu_device()],
        ):
            engine = InferenceEngineService()
            await engine.initialize()
            result = await engine.unload_model("nonexistent")
            assert result is True
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_load_unknown_model_returns_false(self):
        with patch(
            "tools.gimo_server.inference.engine_service.get_devices",
            return_value=[_cpu_device()],
        ):
            engine = InferenceEngineService()
            await engine.initialize()
            result = await engine.load_model("unknown-model", HardwareTarget.CPU)
            assert result is False
            await engine.shutdown()


class TestInferenceEngineServiceInfer:
    @pytest.mark.asyncio
    async def test_infer_unknown_model_returns_error(self):
        with patch(
            "tools.gimo_server.inference.engine_service.get_devices",
            return_value=[_cpu_device()],
        ):
            engine = InferenceEngineService()
            await engine.initialize()
            req = _request()
            result = await engine.infer(req)
            # Unknown model → error field populated
            assert result.error is not None
            assert result.request_id == req.request_id
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_infer_records_metrics(self):
        with patch(
            "tools.gimo_server.inference.engine_service.get_devices",
            return_value=[_cpu_device()],
        ):
            engine = InferenceEngineService()
            await engine.initialize()
            req = _request()
            await engine.infer(req)
            assert engine._metrics._total_requests == 1
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_infer_npu_disabled_no_npu_device(self):
        from tools.gimo_server.inference.contracts import DeviceCapability

        npu = DeviceCapability(
            device_type=HardwareTarget.NPU,
            device_name="Test NPU",
            total_memory_gb=8.0,
            free_memory_gb=4.0,
            execution_providers=[ExecutionProviderType.CPU],
        )
        with patch(
            "tools.gimo_server.inference.engine_service.get_devices",
            return_value=[_cpu_device(), npu],
        ):
            engine = InferenceEngineService(npu_enabled=False)
            await engine.initialize()
            # NPU should be filtered out.
            device_types = [d.device_type for d in engine._devices]
            assert HardwareTarget.NPU not in device_types
            await engine.shutdown()
