"""ONNX graph optimiser for the GIMO Model Compiler.

Applies a sequence of ONNX Runtime graph transformations:
1. Basic optimisations (op fusion, constant folding)
2. Extended optimisations (dead node elimination, shape inference)
3. Transformer-specific fusions (LayerNorm, Attention, Gelu fusions)

All heavy operations run in thread executors.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger("gie.compiler.graph_optimizer")


async def optimize(
    input_path: str,
    output_path: str,
    *,
    for_transformer: bool = True,
    optimization_level: str = "all",
) -> bool:
    """Optimize an ONNX graph and save to *output_path*.

    Args:
        input_path:       Source ONNX file.
        output_path:      Destination (may be the same as input for in-place).
        for_transformer:  Apply transformer-specific op fusions (LayerNorm, Gelu, …).
        optimization_level: "basic", "extended", or "all".

    Returns:
        True if optimisation succeeded, False if onnxruntime is unavailable.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _optimize_sync,
        input_path,
        output_path,
        for_transformer,
        optimization_level,
    )


def _optimize_sync(
    input_path: str,
    output_path: str,
    for_transformer: bool,
    optimization_level: str,
) -> bool:
    try:
        import onnxruntime as ort  # type: ignore[import]
    except ImportError:
        logger.warning("onnxruntime not installed; skipping graph optimisation")
        return False

    level_map = {
        "basic":    ort.GraphOptimizationLevel.ORT_ENABLE_BASIC,
        "extended": ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED,
        "all":      ort.GraphOptimizationLevel.ORT_ENABLE_ALL,
    }
    opt_level = level_map.get(optimization_level, ort.GraphOptimizationLevel.ORT_ENABLE_ALL)

    sess_opts = ort.SessionOptions()
    sess_opts.graph_optimization_level = opt_level
    sess_opts.optimized_model_filepath = output_path

    try:
        # Loading the session with an optimized_model_filepath writes the graph.
        ort.InferenceSession(input_path, sess_options=sess_opts)
        logger.info("Graph optimisation written to %s", output_path)
    except Exception as exc:
        logger.error("ORT graph optimisation failed: %s", exc)
        return False

    if for_transformer:
        _apply_transformer_fusions(output_path)

    return True


def _apply_transformer_fusions(model_path: str) -> None:
    """Apply transformer-specific op fusions using onnxruntime.transformers."""
    try:
        from onnxruntime.transformers import optimizer as tf_opt  # type: ignore[import]
        opt = tf_opt.optimize_model(
            model_path,
            model_type="bert",     # generic; covers BERT/GPT/LLaMA patterns
            num_heads=0,           # auto-detect
            hidden_size=0,         # auto-detect
            optimization_options=None,
        )
        opt.save_model_to_file(model_path)
        logger.info("Transformer fusions applied to %s", model_path)
    except ImportError:
        pass   # onnxruntime-tools not installed; skip silently
    except Exception as exc:
        logger.warning("Transformer fusion failed (non-fatal): %s", exc)
