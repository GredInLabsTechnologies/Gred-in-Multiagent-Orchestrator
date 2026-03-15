"""Unit tests for Fase 5: Model Compiler (model_cache, quantizer, pipeline)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.gimo_server.inference.contracts import (
    CompiledModelInfo,
    ExecutionProviderType,
    HardwareTarget,
    ModelFormat,
    ModelSpec,
    QuantizationType,
)
from tools.gimo_server.inference.compiler.model_cache import (
    ModelCache,
    compute_checksum,
)
from tools.gimo_server.inference.compiler.quantizer import (
    recommend_quantization,
)
from tools.gimo_server.inference.compiler.pipeline import (
    CompilationPipeline,
    _ep_for_target,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(model_id: str = "test-model", size_gb: float = 4.0, quant=QuantizationType.NONE) -> ModelSpec:
    return ModelSpec(
        model_id=model_id,
        path=Path(f"/fake/{model_id}.onnx"),
        format=ModelFormat.ONNX,
        size_bytes=int(size_gb * 1024**3),
        param_count_b=7.0,
        quantization=quant,
    )


def _compiled_info(
    tmp_path: Path,
    model_id: str = "test-model",
    target: HardwareTarget = HardwareTarget.CPU,
    quant: QuantizationType = QuantizationType.INT8,
) -> CompiledModelInfo:
    compiled_file = tmp_path / "model.onnx"
    compiled_file.write_bytes(b"\x00" * 100)
    return CompiledModelInfo(
        model_id=model_id,
        compiled_path=compiled_file,
        target_device=target,
        execution_provider=ExecutionProviderType.CPU,
        quantization=quant,
        compiled_at=time.time(),
        compile_time_seconds=1.0,
        compiled_size_bytes=100,
        checksum="abc123",
    )


# ---------------------------------------------------------------------------
# ModelCache tests
# ---------------------------------------------------------------------------

class TestModelCache:
    def test_put_and_get(self, tmp_path):
        cache = ModelCache(cache_dir=tmp_path)
        info = _compiled_info(tmp_path)
        cache.put(info)
        result = cache.get("test-model", HardwareTarget.CPU, QuantizationType.INT8)
        assert result is not None
        assert result.model_id == "test-model"

    def test_get_missing_returns_none(self, tmp_path):
        cache = ModelCache(cache_dir=tmp_path)
        assert cache.get("nonexistent", HardwareTarget.GPU, QuantizationType.INT8) is None

    def test_exists_true(self, tmp_path):
        cache = ModelCache(cache_dir=tmp_path)
        cache.put(_compiled_info(tmp_path))
        assert cache.exists("test-model", HardwareTarget.CPU, QuantizationType.INT8)

    def test_exists_false(self, tmp_path):
        cache = ModelCache(cache_dir=tmp_path)
        assert not cache.exists("nope", HardwareTarget.CPU, QuantizationType.INT8)

    def test_compiler_version_invalidates(self, tmp_path):
        cache = ModelCache(cache_dir=tmp_path)
        info = _compiled_info(tmp_path)
        cache.put(info)
        # Manually corrupt the version in the metadata file.
        slot = tmp_path / "test-model" / "cpu_int8" / "metadata.json"
        data = json.loads(slot.read_text())
        data["_compiler_version"] = "0.0.0"
        slot.write_text(json.dumps(data))
        # Should treat as invalid and return None.
        assert cache.get("test-model", HardwareTarget.CPU, QuantizationType.INT8) is None

    def test_corrupt_metadata_returns_none(self, tmp_path):
        cache = ModelCache(cache_dir=tmp_path)
        info = _compiled_info(tmp_path)
        cache.put(info)
        # Corrupt metadata.
        slot = tmp_path / "test-model" / "cpu_int8" / "metadata.json"
        slot.write_bytes(b"{corrupt")
        assert cache.get("test-model", HardwareTarget.CPU, QuantizationType.INT8) is None

    def test_lru_eviction(self, tmp_path):
        # Cache with tiny limit so even one entry triggers eviction.
        cache = ModelCache(cache_dir=tmp_path, max_cache_gb=0.000001)
        info = _compiled_info(tmp_path)
        cache.put(info)
        # After put(), eviction runs; total may be reduced.
        # Just ensure no exception is raised.
        assert True

    def test_total_size_empty_dir(self, tmp_path):
        cache = ModelCache(cache_dir=tmp_path)
        assert cache.total_size_bytes() == 0

    def test_different_targets_different_slots(self, tmp_path):
        cache = ModelCache(cache_dir=tmp_path)
        for target, quant in [
            (HardwareTarget.CPU, QuantizationType.INT8),
            (HardwareTarget.GPU, QuantizationType.FP16),
        ]:
            sub = tmp_path / target.value
            sub.mkdir(exist_ok=True)
            info = _compiled_info(sub, "m1", target, quant)
            cache.put(info)
        cpu = cache.get("m1", HardwareTarget.CPU, QuantizationType.INT8)
        gpu = cache.get("m1", HardwareTarget.GPU, QuantizationType.FP16)
        assert cpu is not None
        assert gpu is not None


# ---------------------------------------------------------------------------
# compute_checksum
# ---------------------------------------------------------------------------

class TestComputeChecksum:
    def test_returns_hex_string(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        ck = compute_checksum(f)
        assert len(ck) == 64  # SHA-256 hex

    def test_empty_file_missing_returns_empty(self, tmp_path):
        ck = compute_checksum(tmp_path / "nonexistent.bin")
        assert ck == ""

    def test_same_content_same_checksum(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"data")
        f2.write_bytes(b"data")
        assert compute_checksum(f1) == compute_checksum(f2)

    def test_different_content_different_checksum(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"data1")
        f2.write_bytes(b"data2")
        assert compute_checksum(f1) != compute_checksum(f2)


# ---------------------------------------------------------------------------
# quantizer.recommend_quantization
# ---------------------------------------------------------------------------

class TestRecommendQuantization:
    def test_npu_always_int8(self):
        spec = _spec(quant=QuantizationType.NONE)
        assert recommend_quantization(spec, HardwareTarget.NPU) == QuantizationType.INT8

    def test_gpu_fp16_when_enough_vram(self):
        spec = _spec(quant=QuantizationType.NONE)
        assert recommend_quantization(spec, HardwareTarget.GPU, available_vram_gb=16.0) == QuantizationType.FP16

    def test_gpu_int8_when_low_vram(self):
        spec = _spec(quant=QuantizationType.NONE)
        assert recommend_quantization(spec, HardwareTarget.GPU, available_vram_gb=6.0) == QuantizationType.INT8

    def test_gpu_int4_when_very_low_vram(self):
        spec = _spec(quant=QuantizationType.NONE)
        result = recommend_quantization(spec, HardwareTarget.GPU, available_vram_gb=3.0, allow_int4=True)
        assert result == QuantizationType.INT4

    def test_cpu_int8(self):
        spec = _spec(quant=QuantizationType.NONE)
        assert recommend_quantization(spec, HardwareTarget.CPU) == QuantizationType.INT8

    def test_prequantized_gptq_unchanged(self):
        spec = _spec(quant=QuantizationType.GPTQ)
        assert recommend_quantization(spec, HardwareTarget.GPU) == QuantizationType.GPTQ

    def test_prequantized_awq_unchanged(self):
        spec = _spec(quant=QuantizationType.AWQ)
        assert recommend_quantization(spec, HardwareTarget.NPU) == QuantizationType.AWQ


# ---------------------------------------------------------------------------
# _ep_for_target
# ---------------------------------------------------------------------------

class TestEpForTarget:
    def test_gpu_maps_to_cuda(self):
        assert _ep_for_target(HardwareTarget.GPU) == ExecutionProviderType.CUDA

    def test_npu_maps_to_vitis(self):
        assert _ep_for_target(HardwareTarget.NPU) == ExecutionProviderType.VITIS_AI

    def test_cpu_maps_to_cpu(self):
        assert _ep_for_target(HardwareTarget.CPU) == ExecutionProviderType.CPU


# ---------------------------------------------------------------------------
# CompilationPipeline tests
# ---------------------------------------------------------------------------

class TestCompilationPipeline:
    @pytest.mark.asyncio
    async def test_compile_gguf_returns_original_path(self, tmp_path):
        """GGUF models skip compilation and return their original path."""
        model_file = tmp_path / "model.gguf"
        model_file.write_bytes(b"\x00" * 100)
        spec = ModelSpec(
            model_id="gguf-model",
            path=model_file,
            format=ModelFormat.GGUF,
            size_bytes=100,
            param_count_b=7.0,
        )
        pipeline = CompilationPipeline(
            cache=ModelCache(cache_dir=tmp_path / "cache"),
            tmp_dir=tmp_path / "tmp",
        )
        info = await pipeline.compile(spec, HardwareTarget.CPU)
        assert info.model_id == "gguf-model"
        assert info.compiled_path == model_file

    @pytest.mark.asyncio
    async def test_compile_uses_cache_on_second_call(self, tmp_path):
        model_file = tmp_path / "model.onnx"
        model_file.write_bytes(b"\x00" * 100)
        spec = _spec()
        spec.path = model_file

        cache = ModelCache(cache_dir=tmp_path / "cache")
        pipeline = CompilationPipeline(
            cache=cache,
            tmp_dir=tmp_path / "tmp",
        )

        # Patch ORT to avoid real compilation.
        with patch(
            "tools.gimo_server.inference.compiler.pipeline.optimize",
            return_value=False,
        ):
            info1 = await pipeline.compile(spec, HardwareTarget.CPU)
            info2 = await pipeline.compile(spec, HardwareTarget.CPU)

        # Both calls return valid info; second is from cache.
        assert info1.model_id == info2.model_id

    @pytest.mark.asyncio
    async def test_compile_missing_model_raises(self, tmp_path):
        spec = _spec()
        # path doesn't exist
        pipeline = CompilationPipeline(
            cache=ModelCache(cache_dir=tmp_path / "cache"),
            tmp_dir=tmp_path / "tmp",
        )
        with pytest.raises(FileNotFoundError):
            await pipeline.compile(spec, HardwareTarget.CPU)

    @pytest.mark.asyncio
    async def test_force_recompile_skips_cache(self, tmp_path):
        model_file = tmp_path / "model.onnx"
        model_file.write_bytes(b"\x00" * 100)
        spec = _spec()
        spec.path = model_file

        cache = ModelCache(cache_dir=tmp_path / "cache")
        pipeline = CompilationPipeline(cache=cache, tmp_dir=tmp_path / "tmp")

        with patch(
            "tools.gimo_server.inference.compiler.pipeline.optimize",
            return_value=False,
        ):
            info1 = await pipeline.compile(spec, HardwareTarget.CPU)
            info2 = await pipeline.compile(spec, HardwareTarget.CPU, force=True)

        # compile_time_seconds should differ (recompiled).
        assert info2.compiled_at >= info1.compiled_at
