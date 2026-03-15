"""GGUF / llama-cpp-python adapter for the GIMO Inference Engine.

Wraps ``llama_cpp.Llama`` and implements the :class:`RuntimeAdapter` protocol.
Handles dynamic layer-offloading based on available VRAM so callers only need
to specify a ``HardwareTarget``.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..contracts import (
    ExecutionProviderType,
    HardwareTarget,
    ModelFormat,
    ModelSpec,
)
from .base_adapter import SessionHandle

logger = logging.getLogger("gie.runtime.gguf")

# ---------------------------------------------------------------------------
# Optional import
# ---------------------------------------------------------------------------
try:
    import llama_cpp  # type: ignore[import]
    _LLAMA_AVAILABLE = True
except ImportError:
    _LLAMA_AVAILABLE = False


# ---------------------------------------------------------------------------
# Bytes per parameter for common quantizations (used for layer estimation)
# ---------------------------------------------------------------------------
_BYTES_PER_PARAM = {
    "none":  4.0,   # FP32
    "fp16":  2.0,
    "bf16":  2.0,
    "int8":  1.0,
    "int4":  0.5,
    "q4_0":  0.5,
    "q4_k":  0.5,
    "q5_0":  0.625,
    "q8_0":  1.0,
    "gptq":  0.5,
    "awq":   0.5,
}


def _bytes_per_param(quant: str) -> float:
    return _BYTES_PER_PARAM.get(quant.lower(), 2.0)


def _estimate_gpu_layers(
    param_billions: float,
    quant: str,
    vram_free_gb: float,
    *,
    reserve_vram_gb: float = 0.5,
    num_layers_total: int = 32,
) -> int:
    """Estimate how many transformer layers can be offloaded to GPU.

    Assumes roughly equal layer sizes.  Returns -1 for "all layers to GPU".
    """
    if vram_free_gb <= 0:
        return 0

    usable_vram_gb = max(0.0, vram_free_gb - reserve_vram_gb)
    total_model_gb = param_billions * 1e9 * _bytes_per_param(quant) / 1e9

    if total_model_gb <= 0 or num_layers_total <= 0:
        return 0

    if usable_vram_gb >= total_model_gb:
        return -1  # everything fits

    ratio = usable_vram_gb / total_model_gb
    return max(0, math.floor(ratio * num_layers_total))


class _GgufSessionHandle(SessionHandle):
    """SessionHandle that carries the llama_cpp.Llama instance."""
    pass  # _backend holds the Llama instance


# ---------------------------------------------------------------------------
# GgufAdapter
# ---------------------------------------------------------------------------

class GgufAdapter:
    """llama-cpp-python backend for GGUF models.

    Usage::

        adapter = GgufAdapter()
        handle  = await adapter.load_model(spec, HardwareTarget.GPU)
        outputs = await adapter.run(handle, {"prompt": "Hello!", "max_tokens": 128})
        await adapter.unload(handle)

    Input dict for ``run()``::

        {
            "prompt":      str,          # required
            "max_tokens":  int,          # optional, default 256
            "temperature": float,        # optional, default 0.7
            "top_p":       float,        # optional, default 0.95
            "stop":        list[str],    # optional stop sequences
        }

    Output dict::

        {
            "text":            str,      # generated text
            "tokens_generated": int,
            "tokens_prompt":    int,
        }
    """

    def __init__(
        self,
        *,
        vram_free_gb: float = 0.0,
    ) -> None:
        """
        Args:
            vram_free_gb: Free GPU VRAM in GB used for layer-offload estimation.
                          Pass 0 for CPU-only inference.
        """
        if not _LLAMA_AVAILABLE:
            logger.warning("llama-cpp-python not installed — GgufAdapter will raise on use")
        self._vram_free_gb = vram_free_gb

    # ------------------------------------------------------------------
    # RuntimeAdapter protocol
    # ------------------------------------------------------------------

    def supports_format(self, fmt: str) -> bool:
        return fmt == ModelFormat.GGUF.value

    def get_available_providers(self) -> List[ExecutionProviderType]:
        # GGUF uses its own CUDA/Metal backend, not ORT EPs.
        # We report the effective EP so the session pool can track it.
        if _LLAMA_AVAILABLE and self._vram_free_gb > 0:
            return [ExecutionProviderType.CUDA, ExecutionProviderType.CPU]
        return [ExecutionProviderType.CPU]

    def get_provider_options(self, ep: ExecutionProviderType) -> Dict[str, Any]:
        return {}

    async def load_model(
        self,
        spec: ModelSpec,
        device: HardwareTarget,
    ) -> SessionHandle:
        if not _LLAMA_AVAILABLE:
            raise ImportError(
                "llama-cpp-python is required for GGUF models — "
                "pip install llama-cpp-python"
            )

        model_path = Path(spec.path)
        if not model_path.exists():
            raise FileNotFoundError(f"GGUF model not found: {model_path}")

        quant_str = spec.quantization.value if spec.quantization else "none"
        n_gpu_layers = self._compute_gpu_layers(spec, device, quant_str)

        # n_ctx: number of tokens in the context window.
        n_ctx = min(spec.max_sequence_length, 4096)

        logger.info(
            "Loading GGUF model %s (n_gpu_layers=%s, ctx=%d)",
            spec.model_id,
            "all" if n_gpu_layers == -1 else n_gpu_layers,
            n_ctx,
        )

        def _load() -> "llama_cpp.Llama":
            return llama_cpp.Llama(
                model_path=str(model_path),
                n_gpu_layers=n_gpu_layers,
                n_ctx=n_ctx,
                verbose=False,
            )

        loop = asyncio.get_running_loop()
        llama = await loop.run_in_executor(None, _load)

        mem_mb = (spec.size_bytes / 1024 / 1024) * 1.1  # rough estimate
        active_ep = (
            ExecutionProviderType.CUDA
            if n_gpu_layers != 0
            else ExecutionProviderType.CPU
        )

        handle = _GgufSessionHandle(
            model_id=spec.model_id,
            model_path=model_path,
            hardware_target=device,
            execution_provider=active_ep,
            memory_mb=mem_mb,
            last_used=time.monotonic(),
            _backend=llama,
        )
        logger.info("GGUF model %s loaded (EP=%s)", spec.model_id, active_ep.value)
        return handle

    async def run(
        self,
        session: SessionHandle,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not _LLAMA_AVAILABLE:
            raise ImportError("llama-cpp-python is required")

        llama: "llama_cpp.Llama" = session._backend
        if llama is None:
            raise RuntimeError(f"Session {session.session_id} is no longer valid")

        prompt: str = inputs.get("prompt", "")
        max_tokens: int = int(inputs.get("max_tokens", 256))
        temperature: float = float(inputs.get("temperature", 0.7))
        top_p: float = float(inputs.get("top_p", 0.95))
        stop: Optional[List[str]] = inputs.get("stop")

        def _infer() -> Dict[str, Any]:
            response = llama(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                stop=stop or [],
                echo=False,
            )
            choice = response["choices"][0]
            usage = response.get("usage", {})
            return {
                "text": choice["text"],
                "tokens_generated": usage.get("completion_tokens", 0),
                "tokens_prompt": usage.get("prompt_tokens", 0),
                "finish_reason": choice.get("finish_reason", ""),
            }

        loop = asyncio.get_running_loop()
        session.last_used = time.monotonic()
        return await loop.run_in_executor(None, _infer)

    async def unload(self, session: SessionHandle) -> None:
        if session._backend is not None:
            # llama_cpp.Llama releases native memory on __del__.
            session._backend = None
        logger.debug("GGUF session %s unloaded", session.session_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_gpu_layers(
        self,
        spec: ModelSpec,
        device: HardwareTarget,
        quant_str: str,
    ) -> int:
        """Determine n_gpu_layers based on target device and available VRAM."""
        if device == HardwareTarget.CPU:
            return 0
        if device == HardwareTarget.GPU:
            if self._vram_free_gb <= 0:
                return 0
            # Estimate number of layers; GGUF files typically embed this info
            # but we use a safe default of 32 for transformer architectures.
            num_layers = spec.metadata.get("num_layers", 32)
            return _estimate_gpu_layers(
                spec.param_count_b,
                quant_str,
                self._vram_free_gb,
                num_layers_total=num_layers,
            )
        if device == HardwareTarget.NPU:
            # NPU not natively supported by llama.cpp; fall back to CPU.
            logger.warning("NPU target not supported by GgufAdapter; using CPU")
            return 0
        # AUTO: try GPU, fall back to CPU layer count.
        if self._vram_free_gb > 0:
            return _estimate_gpu_layers(
                spec.param_count_b,
                quant_str,
                self._vram_free_gb,
            )
        return 0
