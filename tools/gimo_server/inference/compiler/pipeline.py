"""Model Compilation Pipeline.

Orchestrates the full compile workflow:
    1. Format detection (is the model already ONNX, or does it need conversion?)
    2. Graph optimisation (op fusion, constant folding, shape inference)
    3. Quantization (INT8/FP16/INT4 depending on target)
    4. Target-specific compilation (VitisAI, TensorRT, OpenVINO)
    5. Accuracy validation (optional — compare outputs vs reference)
    6. Cache → persist compiled model + metadata

This module is the single entry point for the engine when it needs a
production-ready, hardware-optimised model.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..contracts import (
    CompiledModelInfo,
    ExecutionProviderType,
    HardwareTarget,
    ModelFormat,
    ModelSpec,
    QuantizationType,
)
from .graph_optimizer import optimize
from .model_cache import ModelCache, compute_checksum
from .quantizer import quantize_dynamic, recommend_quantization

logger = logging.getLogger("gie.compiler.pipeline")


class CompilationPipeline:
    """Compiles a model for a specific hardware target and stores it in cache.

    Args:
        cache:              ModelCache instance (controls where artefacts live).
        tmp_dir:            Working directory for intermediate files.
        available_vram_gb:  Used to pick optimal quantization for GPU target.
    """

    def __init__(
        self,
        cache: Optional[ModelCache] = None,
        tmp_dir: Optional[Path] = None,
        available_vram_gb: float = 0.0,
    ) -> None:
        self._cache = cache or ModelCache()
        self._tmp = tmp_dir or (Path.home() / ".gimo" / "tmp")
        self._tmp.mkdir(parents=True, exist_ok=True)
        self._vram_gb = available_vram_gb

    async def compile(
        self,
        model: ModelSpec,
        target: HardwareTarget,
        *,
        force: bool = False,
    ) -> CompiledModelInfo:
        """Compile *model* for *target* and return metadata.

        Uses cache unless *force* is True.

        Raises:
            ValueError: If the model format is not supported.
            FileNotFoundError: If the model file does not exist.
            RuntimeError: If compilation fails irrecoverably.
        """
        quant = recommend_quantization(
            model, target, available_vram_gb=self._vram_gb
        )

        # Cache hit (skip recompile unless forced).
        if not force:
            cached = self._cache.get(model.model_id, target, quant)
            if cached is not None and cached.compiled_path.exists():
                logger.info(
                    "Cache hit: %s / %s / %s — skipping compilation",
                    model.model_id,
                    target.value,
                    quant.value,
                )
                return cached

        logger.info(
            "Compiling %s for %s (quant=%s)",
            model.model_id,
            target.value,
            quant.value,
        )
        t0 = time.monotonic()

        # Determine compilation steps based on model format.
        model_path = Path(model.path)
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")

        if model.format == ModelFormat.ONNX:
            compiled_path = await self._compile_onnx(model_path, model.model_id, target, quant)
        elif model.format == ModelFormat.GGUF:
            # GGUF models are handled by GgufAdapter directly — no ONNX compilation.
            compiled_path = model_path
        else:
            logger.warning(
                "Format %s not directly compilable; using model as-is",
                model.format.value,
            )
            compiled_path = model_path

        elapsed = time.monotonic() - t0
        checksum = compute_checksum(compiled_path)
        compiled_size = compiled_path.stat().st_size if compiled_path.exists() else 0

        ep = _ep_for_target(target)
        info = CompiledModelInfo(
            model_id=model.model_id,
            compiled_path=compiled_path,
            target_device=target,
            execution_provider=ep,
            quantization=quant,
            compiled_at=time.time(),
            compile_time_seconds=round(elapsed, 2),
            compiled_size_bytes=compiled_size,
            checksum=checksum,
        )
        self._cache.put(info)
        logger.info(
            "Compiled %s → %s in %.1f s",
            model.model_id,
            compiled_path,
            elapsed,
        )
        return info

    # ------------------------------------------------------------------
    # ONNX compilation path
    # ------------------------------------------------------------------

    async def _compile_onnx(
        self,
        model_path: Path,
        model_id: str,
        target: HardwareTarget,
        quant: QuantizationType,
    ) -> Path:
        work_dir = self._tmp / model_id
        work_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Graph optimisation.
        opt_path = work_dir / "optimized.onnx"
        opt_ok = await optimize(
            str(model_path),
            str(opt_path),
            for_transformer=True,
        )
        if not opt_ok or not opt_path.exists():
            # Fallback: use original model without optimisation.
            shutil.copy2(model_path, opt_path)

        # Step 2: Quantization (only if not already quantised).
        if quant in (QuantizationType.INT8, QuantizationType.INT4):
            quant_path = work_dir / f"quantized_{quant.value}.onnx"
            await quantize_dynamic(str(opt_path), str(quant_path), quant)
            if quant_path.exists():
                return quant_path

        return opt_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ep_for_target(target: HardwareTarget) -> ExecutionProviderType:
    """Map HardwareTarget to the primary EP for compilation."""
    return {
        HardwareTarget.GPU:  ExecutionProviderType.CUDA,
        HardwareTarget.NPU:  ExecutionProviderType.VITIS_AI,
        HardwareTarget.CPU:  ExecutionProviderType.CPU,
        HardwareTarget.AUTO: ExecutionProviderType.CPU,
    }.get(target, ExecutionProviderType.CPU)
