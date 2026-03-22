"""Unit tests for OnnxAdapter — onnxruntime fully mocked."""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Provide a minimal onnxruntime stub so the module can be imported without
# the real library installed.
# ---------------------------------------------------------------------------

def _make_ort_stub() -> types.ModuleType:
    ort = types.ModuleType("onnxruntime")

    class _SessionOptions:
        intra_op_num_threads = 0
        inter_op_num_threads = 0
        execution_mode = None
        graph_optimization_level = None
        enable_cpu_mem_arena = True
        enable_mem_pattern = True

    class _ExecutionMode:
        ORT_PARALLEL = 1
        ORT_SEQUENTIAL = 0

    class _GraphOptimizationLevel:
        ORT_ENABLE_ALL = 3
        ORT_ENABLE_BASIC = 1

    class _InferenceSession:
        def __init__(self, path, sess_options=None, providers=None, provider_options=None):
            self._path = path
            self._providers = providers or []

        def get_outputs(self):
            out = MagicMock()
            out.name = "logits"
            return [out]

        def run(self, output_names, inputs):
            return [[0.0] * 10]

        def io_binding(self):
            raise RuntimeError("io_binding not available in stub")

    ort.SessionOptions = _SessionOptions
    ort.ExecutionMode = _ExecutionMode
    ort.GraphOptimizationLevel = _GraphOptimizationLevel
    ort.InferenceSession = _InferenceSession
    ort.get_available_providers = lambda: [
        "CPUExecutionProvider",
        "CUDAExecutionProvider",
    ]
    return ort


# Inyectar stub y forzar reimportación del módulo para aislar del estado global.
_ort_stub = _make_ort_stub()
sys.modules["onnxruntime"] = _ort_stub

_onnx_mod_key = "tools.gimo_server.inference.runtime.onnx_adapter"
_base_mod_key = "tools.gimo_server.inference.runtime.base_adapter"

# Forzar reimportación de ambos módulos para que recojan el stub fresco
for _key in [_base_mod_key, _onnx_mod_key]:
    if _key in sys.modules:
        importlib.reload(sys.modules[_key])

from tools.gimo_server.inference.contracts import (
    ExecutionProviderType,
    HardwareTarget,
    ModelFormat,
    ModelSpec,
    QuantizationType,
)
from tools.gimo_server.inference.runtime.onnx_adapter import OnnxAdapter
from tools.gimo_server.inference.runtime.base_adapter import select_ep_chain


@pytest.fixture(autouse=True)
def _ensure_ort_stub():
    """Garantizar que el stub de onnxruntime esté activo para cada test."""
    sys.modules["onnxruntime"] = _ort_stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def spec(tmp_path: Path) -> ModelSpec:
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"\x00" * 1024)  # fake 1 KB model
    return ModelSpec(
        model_id="test-model",
        path=model_file,
        format=ModelFormat.ONNX,
        size_bytes=1024,
        param_count_b=0.1,
        quantization=QuantizationType.FP16,
    )


@pytest.fixture()
def adapter() -> OnnxAdapter:
    return OnnxAdapter()


# ---------------------------------------------------------------------------
# Tests — select_ep_chain
# ---------------------------------------------------------------------------

class TestSelectEpChain:
    def test_gpu_chain_prefers_cuda(self):
        available = [ExecutionProviderType.CPU, ExecutionProviderType.CUDA]
        chain = select_ep_chain(HardwareTarget.GPU, available)
        assert chain[0] == ExecutionProviderType.CUDA

    def test_npu_chain_prefers_vitis(self):
        available = [ExecutionProviderType.CPU, ExecutionProviderType.VITIS_AI]
        chain = select_ep_chain(HardwareTarget.NPU, available)
        assert chain[0] == ExecutionProviderType.VITIS_AI

    def test_always_ends_with_cpu(self):
        chain = select_ep_chain(HardwareTarget.GPU, [ExecutionProviderType.CPU])
        assert chain[-1] == ExecutionProviderType.CPU

    def test_empty_available_returns_cpu_only(self):
        chain = select_ep_chain(HardwareTarget.GPU, [])
        assert chain == [ExecutionProviderType.CPU]

    def test_cpu_target_only_cpu(self):
        chain = select_ep_chain(HardwareTarget.CPU, [ExecutionProviderType.CUDA, ExecutionProviderType.CPU])
        assert chain == [ExecutionProviderType.CPU]


# ---------------------------------------------------------------------------
# Tests — OnnxAdapter.supports_format
# ---------------------------------------------------------------------------

class TestOnnxAdapterSupportsFormat:
    def test_supports_onnx(self, adapter):
        assert adapter.supports_format("onnx") is True

    def test_supports_openvino(self, adapter):
        assert adapter.supports_format("openvino") is True

    def test_rejects_gguf(self, adapter):
        assert adapter.supports_format("gguf") is False

    def test_rejects_safetensors(self, adapter):
        assert adapter.supports_format("safetensors") is False


# ---------------------------------------------------------------------------
# Tests — OnnxAdapter.get_available_providers
# ---------------------------------------------------------------------------

class TestGetAvailableProviders:
    def test_returns_list(self, adapter):
        providers = adapter.get_available_providers()
        assert isinstance(providers, list)

    def test_cpu_always_present(self, adapter):
        providers = adapter.get_available_providers()
        assert ExecutionProviderType.CPU in providers

    def test_cuda_detected_from_stub(self, adapter):
        providers = adapter.get_available_providers()
        assert ExecutionProviderType.CUDA in providers


# ---------------------------------------------------------------------------
# Tests — OnnxAdapter.load_model
# ---------------------------------------------------------------------------

class TestLoadModel:
    @pytest.mark.asyncio
    async def test_load_cpu(self, adapter, spec):
        handle = await adapter.load_model(spec, HardwareTarget.CPU)
        assert handle.model_id == "test-model"
        assert handle.hardware_target == HardwareTarget.CPU
        assert handle._backend is not None
        assert handle.memory_mb > 0

    @pytest.mark.asyncio
    async def test_load_gpu(self, adapter, spec):
        handle = await adapter.load_model(spec, HardwareTarget.GPU)
        # CUDA EP is in the stub, so it should be selected.
        assert handle.execution_provider == ExecutionProviderType.CUDA

    @pytest.mark.asyncio
    async def test_load_missing_file_raises(self, adapter):
        bad_spec = ModelSpec(
            model_id="ghost",
            path=Path("/nonexistent/model.onnx"),
            format=ModelFormat.ONNX,
        )
        with pytest.raises(FileNotFoundError):
            await adapter.load_model(bad_spec, HardwareTarget.CPU)

    @pytest.mark.asyncio
    async def test_session_id_unique(self, adapter, spec):
        h1 = await adapter.load_model(spec, HardwareTarget.CPU)
        h2 = await adapter.load_model(spec, HardwareTarget.CPU)
        assert h1.session_id != h2.session_id


# ---------------------------------------------------------------------------
# Tests — OnnxAdapter.run
# ---------------------------------------------------------------------------

class TestRunInference:
    @pytest.mark.asyncio
    async def test_run_returns_dict(self, adapter, spec):
        handle = await adapter.load_model(spec, HardwareTarget.CPU)
        # Pass a plain Python list — the stub's run() accepts any iterable.
        outputs = await adapter.run(handle, {"input_ids": [0] * 10})
        assert isinstance(outputs, dict)
        assert "logits" in outputs

    @pytest.mark.asyncio
    async def test_run_after_unload_raises(self, adapter, spec):
        handle = await adapter.load_model(spec, HardwareTarget.CPU)
        await adapter.unload(handle)
        with pytest.raises(RuntimeError):
            await adapter.run(handle, {"input_ids": [0]})


# ---------------------------------------------------------------------------
# Tests — OnnxAdapter.unload
# ---------------------------------------------------------------------------

class TestUnload:
    @pytest.mark.asyncio
    async def test_unload_clears_backend(self, adapter, spec):
        handle = await adapter.load_model(spec, HardwareTarget.CPU)
        await adapter.unload(handle)
        assert handle._backend is None

    @pytest.mark.asyncio
    async def test_double_unload_is_safe(self, adapter, spec):
        handle = await adapter.load_model(spec, HardwareTarget.CPU)
        await adapter.unload(handle)
        await adapter.unload(handle)  # should not raise
