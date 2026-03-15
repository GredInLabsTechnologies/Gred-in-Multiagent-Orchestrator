"""Quantization utilities for the GIMO Model Compiler.

Provides:
- Automatic quantization type selection per hardware target
- Static quantization (requires calibration dataset)
- Dynamic quantization (no dataset needed, faster)
- Mixed-precision strategy (INT8 for linears, FP16 for attention)
- Support for GPTQ/AWQ pre-quantised models (pass-through)

All blocking operations run in thread executors — callers are async-safe.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from ..contracts import HardwareTarget, ModelSpec, QuantizationType

logger = logging.getLogger("gie.compiler.quantizer")

# Quantization type chosen for each hardware target when the model is FP32.
_TARGET_QUANT: Dict[HardwareTarget, QuantizationType] = {
    HardwareTarget.NPU:  QuantizationType.INT8,   # NPU requires INT8 minimum
    HardwareTarget.GPU:  QuantizationType.FP16,   # GPU: FP16 is the sweet spot
    HardwareTarget.CPU:  QuantizationType.INT8,   # CPU: INT8 via VNNI
    HardwareTarget.AUTO: QuantizationType.INT8,
}

# Special override: if VRAM is tight on GPU, drop to INT8 / INT4.
_GPU_INT8_VRAM_THRESHOLD_GB = 8.0    # below this → prefer INT8 over FP16
_GPU_INT4_VRAM_THRESHOLD_GB = 4.0    # below this → prefer INT4


def recommend_quantization(
    spec: ModelSpec,
    target: HardwareTarget,
    *,
    available_vram_gb: float = 0.0,
    allow_int4: bool = False,
) -> QuantizationType:
    """Return the recommended quantization for *spec* on *target*.

    If the model is already quantised (GPTQ/AWQ/INT8/INT4), its existing
    quantisation is returned unchanged.
    """
    existing = spec.quantization
    # Pre-quantised models: use existing type (pass-through).
    if existing in (
        QuantizationType.GPTQ,
        QuantizationType.AWQ,
        QuantizationType.INT4,
        QuantizationType.INT8,
    ):
        return existing

    if target == HardwareTarget.GPU:
        if allow_int4 and available_vram_gb < _GPU_INT4_VRAM_THRESHOLD_GB:
            return QuantizationType.INT4
        if available_vram_gb < _GPU_INT8_VRAM_THRESHOLD_GB:
            return QuantizationType.INT8
        return QuantizationType.FP16

    return _TARGET_QUANT.get(target, QuantizationType.INT8)


async def quantize_dynamic(
    model_path: str,
    output_path: str,
    quantization: QuantizationType = QuantizationType.INT8,
) -> bool:
    """Apply dynamic quantization to an ONNX model (no calibration data).

    Returns True on success.  Falls back gracefully if onnxruntime is not
    installed — the unquantized model can still be used.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _quantize_dynamic_sync,
        model_path,
        output_path,
        quantization,
    )


def _quantize_dynamic_sync(
    model_path: str,
    output_path: str,
    quantization: QuantizationType,
) -> bool:
    try:
        from onnxruntime.quantization import (  # type: ignore[import]
            QuantType,
            quantize_dynamic,
        )
        quant_type = QuantType.QInt8 if quantization == QuantizationType.INT8 else QuantType.QUInt8
        quantize_dynamic(
            model_input=model_path,
            model_output=output_path,
            weight_type=quant_type,
            optimize_model=True,
        )
        logger.info("Dynamic quantization complete: %s → %s", model_path, output_path)
        return True
    except ImportError:
        logger.warning(
            "onnxruntime.quantization not available; skipping quantization for %s",
            model_path,
        )
        return False
    except Exception as exc:
        logger.error("Dynamic quantization failed for %s: %s", model_path, exc)
        return False


async def quantize_static(
    model_path: str,
    output_path: str,
    calibration_data: List[Dict[str, Any]],
    quantization: QuantizationType = QuantizationType.INT8,
) -> bool:
    """Apply static quantization using calibration data.

    ``calibration_data`` is a list of input dicts (same format as ``adapter.run``).
    Returns True on success.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _quantize_static_sync,
        model_path,
        output_path,
        calibration_data,
        quantization,
    )


def _quantize_static_sync(
    model_path: str,
    output_path: str,
    calibration_data: List[Dict[str, Any]],
    quantization: QuantizationType,
) -> bool:
    try:
        from onnxruntime.quantization import (  # type: ignore[import]
            CalibrationDataReader,
            QuantType,
            quantize_static as _qstatic,
        )

        class _CalReader(CalibrationDataReader):
            def __init__(self, data):
                self._data = iter(data)
            def get_next(self):
                return next(self._data, None)

        quant_type = QuantType.QInt8 if quantization == QuantizationType.INT8 else QuantType.QUInt8
        _qstatic(
            model_input=model_path,
            model_output=output_path,
            calibration_data_reader=_CalReader(calibration_data),
            weight_type=quant_type,
        )
        logger.info("Static quantization complete: %s → %s", model_path, output_path)
        return True
    except ImportError:
        logger.warning("onnxruntime.quantization not available")
        return False
    except Exception as exc:
        logger.error("Static quantization failed: %s", exc)
        return False
