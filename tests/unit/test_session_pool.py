"""Unit tests for SessionPool — LRU eviction and concurrent access."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.gimo_server.inference.contracts import (
    ExecutionProviderType,
    HardwareTarget,
    ModelFormat,
    ModelSpec,
    QuantizationType,
)
from tools.gimo_server.inference.runtime.base_adapter import SessionHandle
from tools.gimo_server.inference.runtime.session_pool import SessionPool, _pool_key


# ---------------------------------------------------------------------------
# Helpers — fake adapter
# ---------------------------------------------------------------------------

class FakeAdapter:
    """Minimal in-memory adapter stub."""

    def __init__(self, memory_per_session_mb: float = 1000.0) -> None:
        self._mem = memory_per_session_mb
        self.loaded: List[str] = []
        self.unloaded: List[str] = []

    def supports_format(self, fmt: str) -> bool:
        return True

    def get_available_providers(self) -> List[ExecutionProviderType]:
        return [ExecutionProviderType.CPU]

    def get_provider_options(self, ep: ExecutionProviderType) -> Dict[str, Any]:
        return {}

    async def load_model(self, spec: ModelSpec, device: HardwareTarget) -> SessionHandle:
        self.loaded.append(spec.model_id)
        return SessionHandle(
            model_id=spec.model_id,
            model_path=spec.path,
            hardware_target=device,
            execution_provider=ExecutionProviderType.CPU,
            memory_mb=self._mem,
            last_used=time.monotonic(),
            _backend=object(),
        )

    async def run(self, session: SessionHandle, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"output": 42}

    async def unload(self, session: SessionHandle) -> None:
        self.unloaded.append(session.model_id)
        session._backend = None


def _spec(model_id: str) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        path=Path(f"/fake/{model_id}.onnx"),
        format=ModelFormat.ONNX,
        size_bytes=0,
    )


# ---------------------------------------------------------------------------
# Tests — basic get_or_load
# ---------------------------------------------------------------------------

class TestGetOrLoad:
    @pytest.mark.asyncio
    async def test_first_call_triggers_load(self):
        pool = SessionPool(max_sessions=4)
        adapter = FakeAdapter()
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        assert "m1" in adapter.loaded

    @pytest.mark.asyncio
    async def test_second_call_returns_cached(self):
        pool = SessionPool(max_sessions=4)
        adapter = FakeAdapter()
        h1 = await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        h2 = await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        assert h1.session_id == h2.session_id
        assert adapter.loaded.count("m1") == 1

    @pytest.mark.asyncio
    async def test_hit_and_miss_counters(self):
        pool = SessionPool(max_sessions=4)
        adapter = FakeAdapter()
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)  # miss
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)  # hit
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)  # hit
        assert pool.metrics.misses == 1
        assert pool.metrics.hits == 2

    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self):
        pool = SessionPool(max_sessions=4)
        adapter = FakeAdapter()
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)  # miss
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)  # hit
        assert pool.metrics.hit_rate == 0.5


# ---------------------------------------------------------------------------
# Tests — LRU eviction by session count
# ---------------------------------------------------------------------------

class TestEvictionByCount:
    @pytest.mark.asyncio
    async def test_evicts_lru_when_full(self):
        pool = SessionPool(max_sessions=2)
        adapter = FakeAdapter()
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        await pool.get_or_load(_spec("m2"), HardwareTarget.CPU, adapter)
        # m1 is LRU at this point; loading m3 should evict m1.
        await pool.get_or_load(_spec("m3"), HardwareTarget.CPU, adapter)
        assert pool.session_count() == 2
        assert pool.metrics.evictions == 1
        assert "m1" in adapter.unloaded

    @pytest.mark.asyncio
    async def test_recently_accessed_not_evicted(self):
        pool = SessionPool(max_sessions=2)
        adapter = FakeAdapter()
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        await pool.get_or_load(_spec("m2"), HardwareTarget.CPU, adapter)
        # Access m1 to make it MRU.
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        # Now m2 is LRU; loading m3 should evict m2.
        await pool.get_or_load(_spec("m3"), HardwareTarget.CPU, adapter)
        assert "m2" in adapter.unloaded
        assert "m1" not in adapter.unloaded


# ---------------------------------------------------------------------------
# Tests — LRU eviction by memory
# ---------------------------------------------------------------------------

class TestEvictionByMemory:
    @pytest.mark.asyncio
    async def test_evicts_when_memory_exceeded(self):
        # Each session uses 1000 MB; cap at 1500 MB → only 1 fits.
        pool = SessionPool(max_sessions=10, max_memory_mb=1500.0)
        adapter = FakeAdapter(memory_per_session_mb=1000.0)
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        await pool.get_or_load(_spec("m2"), HardwareTarget.CPU, adapter)
        # m1 should be evicted to accommodate m2.
        assert pool.metrics.evictions >= 1
        assert "m1" in adapter.unloaded

    @pytest.mark.asyncio
    async def test_total_memory_tracked(self):
        pool = SessionPool(max_sessions=10, max_memory_mb=99_000.0)
        adapter = FakeAdapter(memory_per_session_mb=500.0)
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        await pool.get_or_load(_spec("m2"), HardwareTarget.CPU, adapter)
        assert pool.total_memory_mb() == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# Tests — explicit evict
# ---------------------------------------------------------------------------

class TestExplicitEvict:
    @pytest.mark.asyncio
    async def test_evict_specific_model(self):
        pool = SessionPool(max_sessions=4)
        adapter = FakeAdapter()
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        await pool.evict("m1", HardwareTarget.CPU)
        assert not pool.is_loaded("m1", HardwareTarget.CPU)
        assert "m1" in adapter.unloaded

    @pytest.mark.asyncio
    async def test_evict_all_devices(self):
        pool = SessionPool(max_sessions=4)
        adapter = FakeAdapter()
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        await pool.get_or_load(_spec("m1"), HardwareTarget.GPU, adapter)
        await pool.evict("m1")
        assert pool.session_count() == 0
        assert adapter.unloaded.count("m1") == 2

    @pytest.mark.asyncio
    async def test_evict_all(self):
        pool = SessionPool(max_sessions=4)
        adapter = FakeAdapter()
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        await pool.get_or_load(_spec("m2"), HardwareTarget.CPU, adapter)
        await pool.evict_all()
        assert pool.session_count() == 0

    @pytest.mark.asyncio
    async def test_evict_nonexistent_is_noop(self):
        pool = SessionPool(max_sessions=4)
        adapter = FakeAdapter()
        await pool.evict("ghost", HardwareTarget.CPU)  # must not raise
        assert pool.metrics.evictions == 0


# ---------------------------------------------------------------------------
# Tests — loaded_models snapshot
# ---------------------------------------------------------------------------

class TestLoadedModels:
    @pytest.mark.asyncio
    async def test_snapshot_contains_loaded(self):
        pool = SessionPool(max_sessions=4)
        adapter = FakeAdapter()
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        snapshot = pool.loaded_models()
        assert len(snapshot) == 1
        assert snapshot[0]["model_id"] == "m1"

    @pytest.mark.asyncio
    async def test_snapshot_empty_after_evict_all(self):
        pool = SessionPool(max_sessions=4)
        adapter = FakeAdapter()
        await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, adapter)
        await pool.evict_all()
        assert pool.loaded_models() == []


# ---------------------------------------------------------------------------
# Tests — load error tracking
# ---------------------------------------------------------------------------

class TestLoadError:
    @pytest.mark.asyncio
    async def test_load_error_increments_counter(self):
        pool = SessionPool(max_sessions=4)

        class BrokenAdapter(FakeAdapter):
            async def load_model(self, spec, device):
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await pool.get_or_load(_spec("m1"), HardwareTarget.CPU, BrokenAdapter())
        assert pool.metrics.load_errors == 1


# ---------------------------------------------------------------------------
# Tests — _pool_key helper
# ---------------------------------------------------------------------------

class TestPoolKey:
    def test_unique_per_device(self):
        k1 = _pool_key("model", HardwareTarget.CPU)
        k2 = _pool_key("model", HardwareTarget.GPU)
        assert k1 != k2

    def test_same_for_same_args(self):
        assert _pool_key("x", HardwareTarget.NPU) == _pool_key("x", HardwareTarget.NPU)
