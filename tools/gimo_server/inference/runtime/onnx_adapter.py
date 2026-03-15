"""ONNX Runtime adapter for the GIMO Inference Engine.

Wraps ``onnxruntime.InferenceSession`` and implements the :class:`RuntimeAdapter`
protocol.  All ONNX-specific concerns (session options, IO binding, EP selection)
are encapsulated here so the rest of the engine stays backend-agnostic.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..contracts import (
    ExecutionProviderType,
    HardwareTarget,
    ModelFormat,
    ModelSpec,
)
from .base_adapter import EP_PRIORITY, SessionHandle, select_ep_chain

logger = logging.getLogger("gie.runtime.onnx")

# ---------------------------------------------------------------------------
# Optional import — onnxruntime may not be present in all environments.
# The adapter still loads; methods raise ImportError when called.
# ---------------------------------------------------------------------------
try:
    import onnxruntime as ort  # type: ignore[import]
    _ORT_AVAILABLE = True
    _ORT_PROVIDERS: List[str] = ort.get_available_providers()
except ImportError:
    _ORT_AVAILABLE = False
    _ORT_PROVIDERS = []


class _OnnxSessionHandle(SessionHandle):
    """SessionHandle subclass that keeps a reference to the ort session."""
    pass  # _backend holds the ort.InferenceSession


# ---------------------------------------------------------------------------
# Session-option builders
# ---------------------------------------------------------------------------

def _session_options_for(
    device: HardwareTarget,
    *,
    num_threads: Optional[int] = None,
) -> "ort.SessionOptions":
    """Build ``ort.SessionOptions`` tuned for *device*."""
    if not _ORT_AVAILABLE:
        raise ImportError("onnxruntime is not installed")

    opts = ort.SessionOptions()

    if device == HardwareTarget.CPU:
        import os
        physical_cores = os.cpu_count() or 4
        threads = num_threads or physical_cores
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = max(1, threads // 2)
        opts.execution_mode = ort.ExecutionMode.ORT_PARALLEL
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # Memory arena avoids repeated malloc/free on each inference call.
        opts.enable_cpu_mem_arena = True
        opts.enable_mem_pattern = True

    elif device == HardwareTarget.GPU:
        # For GPU we rely on CUDA EP to manage threads; reduce CPU overhead.
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.enable_cpu_mem_arena = False  # GPU manages its own arena

    elif device == HardwareTarget.NPU:
        # NPU providers handle their own threading; keep ORT out of the way.
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        opts.enable_cpu_mem_arena = False

    else:  # AUTO
        opts.intra_op_num_threads = 0  # let ORT decide
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.enable_cpu_mem_arena = True

    return opts


def _provider_options_for(ep: ExecutionProviderType) -> Dict[str, Any]:
    """Return EP-specific option dict understood by onnxruntime."""
    if ep == ExecutionProviderType.CUDA:
        return {
            "device_id": 0,
            "arena_extend_strategy": "kNextPowerOfTwo",
            "gpu_mem_limit": 0,          # 0 = no limit
            "cudnn_conv_algo_search": "EXHAUSTIVE",
            "do_copy_in_default_stream": True,
        }
    if ep == ExecutionProviderType.TENSORRT:
        return {
            "device_id": 0,
            "trt_max_workspace_size": 1 << 30,  # 1 GB
            "trt_fp16_enable": True,
        }
    if ep == ExecutionProviderType.OPENVINO:
        return {"device_type": "CPU"}   # may be overridden to "NPU" for Intel NPU
    if ep == ExecutionProviderType.VITIS_AI:
        return {}  # VitisAI reads config from environment / xclbin file
    if ep == ExecutionProviderType.DIRECTML:
        return {"device_id": 0}
    return {}


# ---------------------------------------------------------------------------
# OnnxAdapter
# ---------------------------------------------------------------------------

class OnnxAdapter:
    """ONNX Runtime backend.

    Usage::

        adapter = OnnxAdapter()
        handle  = await adapter.load_model(spec, HardwareTarget.GPU)
        outputs = await adapter.run(handle, {"input_ids": tensor})
        await adapter.unload(handle)
    """

    def __init__(self) -> None:
        if not _ORT_AVAILABLE:
            logger.warning("onnxruntime not installed — OnnxAdapter will raise on use")
        # Map of raw provider string → ExecutionProviderType for fast lookup.
        self._available: List[ExecutionProviderType] = self._probe_providers()

    # ------------------------------------------------------------------
    # RuntimeAdapter protocol implementation
    # ------------------------------------------------------------------

    def supports_format(self, fmt: str) -> bool:
        return fmt in (ModelFormat.ONNX.value, ModelFormat.OPENVINO.value)

    def get_available_providers(self) -> List[ExecutionProviderType]:
        return list(self._available)

    def get_provider_options(self, ep: ExecutionProviderType) -> Dict[str, Any]:
        return _provider_options_for(ep)

    async def load_model(
        self,
        spec: ModelSpec,
        device: HardwareTarget,
    ) -> SessionHandle:
        """Load an ONNX model and return a session handle.

        Runs the blocking ``ort.InferenceSession()`` call in a thread pool to
        avoid blocking the event loop during IO-heavy model loading.
        """
        if not _ORT_AVAILABLE:
            raise ImportError("onnxruntime is required — pip install onnxruntime")

        model_path = Path(spec.path)
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")

        ep_chain = select_ep_chain(device, self._available)
        providers = [ep.value for ep in ep_chain]
        provider_options = [_provider_options_for(ep) for ep in ep_chain]
        opts = _session_options_for(device)

        logger.info(
            "Loading ONNX model %s on %s via %s",
            spec.model_id,
            device.value,
            [ep.value for ep in ep_chain],
        )

        def _load() -> "ort.InferenceSession":
            return ort.InferenceSession(
                str(model_path),
                sess_options=opts,
                providers=providers,
                provider_options=provider_options,
            )

        loop = asyncio.get_running_loop()
        session = await loop.run_in_executor(None, _load)

        # Estimate memory: model file size × 1.2 overhead for runtime buffers.
        mem_mb = (spec.size_bytes / 1024 / 1024) * 1.2

        # Determine the EP that was actually activated (first in provider list).
        active_ep = ep_chain[0] if ep_chain else ExecutionProviderType.CPU

        handle = _OnnxSessionHandle(
            model_id=spec.model_id,
            model_path=model_path,
            hardware_target=device,
            execution_provider=active_ep,
            memory_mb=mem_mb,
            last_used=time.monotonic(),
            _backend=session,
        )
        logger.info("Model %s loaded (%.0f MB, EP=%s)", spec.model_id, mem_mb, active_ep.value)
        return handle

    async def run(
        self,
        session: SessionHandle,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run inference.  Non-blocking — delegates to thread pool."""
        if not _ORT_AVAILABLE:
            raise ImportError("onnxruntime is required")

        ort_session: "ort.InferenceSession" = session._backend
        if ort_session is None:
            raise RuntimeError(f"Session {session.session_id} has no backend (already unloaded?)")

        # IO binding (zero-copy) when the active EP supports it.
        use_binding = session.execution_provider in (
            ExecutionProviderType.CUDA,
            ExecutionProviderType.TENSORRT,
            ExecutionProviderType.DIRECTML,
            ExecutionProviderType.ROCM,
        )

        def _run() -> Dict[str, Any]:
            if use_binding:
                return self._run_with_binding(ort_session, inputs)
            output_names = [o.name for o in ort_session.get_outputs()]
            results = ort_session.run(output_names, inputs)
            return dict(zip(output_names, results))

        loop = asyncio.get_running_loop()
        session.last_used = time.monotonic()
        return await loop.run_in_executor(None, _run)

    async def unload(self, session: SessionHandle) -> None:
        """Release the ORT session.  The handle is invalid after this call."""
        if session._backend is not None:
            # ort.InferenceSession has no explicit close(); dropping the reference
            # triggers __del__ which frees native memory.
            session._backend = None
        logger.debug("Session %s unloaded", session.session_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _probe_providers() -> List[ExecutionProviderType]:
        """Map raw ORT provider strings to our enum values."""
        if not _ORT_AVAILABLE:
            return []
        mapping = {ep.value: ep for ep in ExecutionProviderType}
        result: List[ExecutionProviderType] = []
        for raw in _ORT_PROVIDERS:
            ep = mapping.get(raw)
            if ep is not None:
                result.append(ep)
        return result

    @staticmethod
    def _run_with_binding(
        ort_session: "ort.InferenceSession",
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """IO-binding path for GPU/NPU EPs (avoids host↔device copies)."""
        try:
            binding = ort_session.io_binding()
            for name, value in inputs.items():
                # value is expected to be a numpy array or OrtValue.
                binding.bind_cpu_input(name, value)
            for output in ort_session.get_outputs():
                binding.bind_output(output.name)
            ort_session.run_with_iobinding(binding)
            output_names = [o.name for o in ort_session.get_outputs()]
            ortvalues = binding.get_outputs()
            return {name: ortval.numpy() for name, ortval in zip(output_names, ortvalues)}
        except Exception as exc:
            # Fall back to standard run if IO binding fails (e.g. driver issue).
            logger.warning("IO binding failed (%s), falling back to standard run", exc)
            output_names = [o.name for o in ort_session.get_outputs()]
            results = ort_session.run(output_names, inputs)
            return dict(zip(output_names, results))
