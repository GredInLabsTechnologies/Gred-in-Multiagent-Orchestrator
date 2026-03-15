"""Telemetry and metrics for the GIMO Inference Engine.

All counters are in-process only (no external time-series DB required).
The metrics dict is exposed via the /api/ops/inference/metrics endpoint.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


@dataclass
class _RequestRecord:
    request_id: str
    model_id: str
    task: str
    device: str
    latency_ms: float
    tokens_generated: int
    tokens_per_second: float
    memory_peak_mb: float
    error: Optional[str]
    timestamp: float = field(default_factory=time.time)


class InferenceMetrics:
    """Collects and aggregates inference telemetry.

    Thread-safe via GIL for simple counters; uses deque for rolling windows.
    """

    def __init__(self, window_size: int = 500) -> None:
        self._window: Deque[_RequestRecord] = deque(maxlen=window_size)
        self._total_requests: int = 0
        self._total_errors: int = 0
        self._total_tokens: int = 0

        # Per-device counters.
        self._device_requests: Dict[str, int] = defaultdict(int)
        self._device_latency_sum_ms: Dict[str, float] = defaultdict(float)
        self._device_tokens: Dict[str, int] = defaultdict(int)

        # Per-task counters.
        self._task_requests: Dict[str, int] = defaultdict(int)
        self._task_latency_sum_ms: Dict[str, float] = defaultdict(float)

        # Model-load latency.
        self._model_load_times: Deque[float] = deque(maxlen=50)

        # Session pool stats (injected by the engine).
        self._pool_hits: int = 0
        self._pool_misses: int = 0
        self._pool_evictions: int = 0

        # Queue depths (snapshotted periodically).
        self._queue_snapshot: Dict[str, int] = {}

        self._started_at: float = time.time()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_request(
        self,
        request_id: str,
        model_id: str,
        task: str,
        device: str,
        latency_ms: float,
        tokens_generated: int = 0,
        tokens_per_second: float = 0.0,
        memory_peak_mb: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        record = _RequestRecord(
            request_id=request_id,
            model_id=model_id,
            task=task,
            device=device,
            latency_ms=latency_ms,
            tokens_generated=tokens_generated,
            tokens_per_second=tokens_per_second,
            memory_peak_mb=memory_peak_mb,
            error=error,
        )
        self._window.append(record)
        self._total_requests += 1
        if error:
            self._total_errors += 1
        self._total_tokens += tokens_generated
        self._device_requests[device] += 1
        self._device_latency_sum_ms[device] += latency_ms
        self._device_tokens[device] += tokens_generated
        self._task_requests[task] += 1
        self._task_latency_sum_ms[task] += latency_ms

    def record_model_load(self, load_time_ms: float) -> None:
        self._model_load_times.append(load_time_ms)

    def update_pool_stats(self, hits: int, misses: int, evictions: int) -> None:
        self._pool_hits = hits
        self._pool_misses = misses
        self._pool_evictions = evictions

    def update_queue_snapshot(self, queue_depths: Dict[str, int]) -> None:
        self._queue_snapshot = dict(queue_depths)

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        window = list(self._window)
        uptime_s = time.time() - self._started_at
        rps = self._total_requests / uptime_s if uptime_s > 0 else 0.0

        # Rolling window averages.
        recent = [r for r in window if r.timestamp > time.time() - 60]
        avg_latency_ms = (
            sum(r.latency_ms for r in recent) / len(recent) if recent else 0.0
        )
        avg_tps = (
            sum(r.tokens_per_second for r in recent) / len(recent) if recent else 0.0
        )

        # Per-device averages.
        device_stats = {}
        for dev, count in self._device_requests.items():
            avg_lat = self._device_latency_sum_ms[dev] / count if count else 0.0
            device_stats[dev] = {
                "requests": count,
                "avg_latency_ms": round(avg_lat, 1),
                "total_tokens": self._device_tokens[dev],
            }

        # Per-task averages.
        task_stats = {}
        for task, count in self._task_requests.items():
            avg_lat = self._task_latency_sum_ms[task] / count if count else 0.0
            task_stats[task] = {
                "requests": count,
                "avg_latency_ms": round(avg_lat, 1),
            }

        # Model load avg.
        loads = list(self._model_load_times)
        avg_load = sum(loads) / len(loads) if loads else 0.0

        # Pool cache hit rate.
        total_pool = self._pool_hits + self._pool_misses
        hit_rate = self._pool_hits / total_pool if total_pool else 0.0

        return {
            "uptime_seconds": round(uptime_s, 1),
            "total_requests": self._total_requests,
            "total_errors": self._total_errors,
            "total_tokens_generated": self._total_tokens,
            "requests_per_second": round(rps, 3),
            "avg_latency_ms_last_60s": round(avg_latency_ms, 1),
            "avg_tokens_per_second_last_60s": round(avg_tps, 1),
            "error_rate": round(
                self._total_errors / self._total_requests, 4
            ) if self._total_requests else 0.0,
            "device_stats": device_stats,
            "task_stats": task_stats,
            "session_pool": {
                "hits": self._pool_hits,
                "misses": self._pool_misses,
                "evictions": self._pool_evictions,
                "hit_rate": round(hit_rate, 3),
            },
            "model_load_avg_ms": round(avg_load, 1),
            "queue_depths": self._queue_snapshot,
        }
