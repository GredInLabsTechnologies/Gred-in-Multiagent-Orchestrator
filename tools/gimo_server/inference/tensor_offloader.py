"""Tensor offloader — double-buffered layer-by-layer prefetch.

Implements the pre-fetch + double-buffer strategy so GPU compute and
CPU→GPU transfer overlap in time:

    Buffer A: GPU processing layer N
    Buffer B: loading layer N+2 from CPU/disk into GPU (async)

When loading is faster than compute (overhead_ratio < 0.3), the user sees
near-native throughput despite having layers in CPU RAM.

This module is intentionally backend-agnostic: it orchestrates transfers
using a simple callback interface so it can work with both ONNX Runtime and
llama-cpp sessions.

NOTE: Full async prefetch requires CUDA pinned memory or equivalent.
      In environments without a GPU, the offloader degrades gracefully to
      sequential loading (no overlap but correct results).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict

logger = logging.getLogger("gie.tensor_offloader")

# Thresholds from the plan.
_EFFICIENT_THRESHOLD = 0.3    # overhead_ratio below this → offloading is efficient
_WARN_THRESHOLD      = 0.5    # above this → warn user to use smaller model


@dataclass
class OffloadMetrics:
    """Performance counters for layer-by-layer offloading."""
    layers_transferred: int = 0
    total_transfer_ms: float = 0.0
    total_compute_ms: float = 0.0

    @property
    def overhead_ratio(self) -> float:
        """transfer_time / compute_time (0 = no overhead, 1 = bottlenecked by IO)."""
        if self.total_compute_ms <= 0:
            return 0.0
        return self.total_transfer_ms / self.total_compute_ms

    def update(self, transfer_ms: float, compute_ms: float) -> None:
        self.layers_transferred += 1
        self.total_transfer_ms += transfer_ms
        self.total_compute_ms  += compute_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layers_transferred": self.layers_transferred,
            "total_transfer_ms": round(self.total_transfer_ms, 1),
            "total_compute_ms": round(self.total_compute_ms, 1),
            "overhead_ratio": round(self.overhead_ratio, 3),
            "efficiency": "good" if self.overhead_ratio < _EFFICIENT_THRESHOLD
                          else ("warn" if self.overhead_ratio < _WARN_THRESHOLD else "poor"),
        }


# ---------------------------------------------------------------------------
# Transfer + Compute callback types
# ---------------------------------------------------------------------------

# A "layer token" is an opaque object produced by load_layer_fn and consumed
# by compute_layer_fn.  The offloader does not inspect its contents.
LayerToken = Any

LoadLayerFn    = Callable[[int], LayerToken]          # load layer N → token
ComputeLayerFn = Callable[[int, LayerToken], Any]     # compute with token


@dataclass
class OffloadContext:
    """Configuration for an offload run."""
    total_layers: int
    load_fn: LoadLayerFn          # synchronous: load layer from CPU/disk
    compute_fn: ComputeLayerFn    # synchronous: run layer on GPU
    prefetch_depth: int = 2       # how many layers ahead to prefetch


async def run_with_prefetch(ctx: OffloadContext) -> OffloadMetrics:
    """Execute all layers with double-buffered prefetch.

    Returns accumulated metrics so the caller can log efficiency.
    """
    metrics = OffloadMetrics()
    loop = asyncio.get_running_loop()

    # Buffer: pre-loaded layer tokens (one per prefetch slot).
    # We maintain a small sliding window of loaded layers.
    buffer: Dict[int, LayerToken] = {}

    async def _prefetch(layer_idx: int) -> None:
        if layer_idx < ctx.total_layers and layer_idx not in buffer:
            t0 = time.monotonic()
            token = await loop.run_in_executor(None, ctx.load_fn, layer_idx)
            elapsed_ms = (time.monotonic() - t0) * 1000
            buffer[layer_idx] = token
            logger.debug("Prefetched layer %d (%.1f ms)", layer_idx, elapsed_ms)

    # Seed the buffer with the first `prefetch_depth` layers.
    await asyncio.gather(*[_prefetch(i) for i in range(min(ctx.prefetch_depth, ctx.total_layers))])

    for i in range(ctx.total_layers):
        # Kick off prefetch for layer i + prefetch_depth while we compute layer i.
        prefetch_task = asyncio.create_task(_prefetch(i + ctx.prefetch_depth))

        # Wait for current layer to be in buffer.
        t_wait = time.monotonic()
        while i not in buffer:
            await asyncio.sleep(0)  # yield; prefetch might be running
        transfer_ms = (time.monotonic() - t_wait) * 1000

        token = buffer.pop(i)

        # Compute (blocking → thread pool).
        t_compute = time.monotonic()
        await loop.run_in_executor(None, ctx.compute_fn, i, token)
        compute_ms = (time.monotonic() - t_compute) * 1000

        metrics.update(transfer_ms, compute_ms)

        # Ensure prefetch task finishes before we move on.
        await prefetch_task

    if metrics.overhead_ratio > _WARN_THRESHOLD:
        logger.warning(
            "Offload overhead ratio %.2f exceeds threshold %.1f — "
            "consider a smaller quantization or model size. "
            "Actual throughput is significantly reduced.",
            metrics.overhead_ratio,
            _WARN_THRESHOLD,
        )
    elif metrics.overhead_ratio < _EFFICIENT_THRESHOLD:
        logger.info(
            "Offload efficient (overhead_ratio=%.2f). "
            "Prefetch is hiding most of the transfer latency.",
            metrics.overhead_ratio,
        )

    return metrics
