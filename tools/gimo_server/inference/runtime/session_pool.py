"""Session pool with LRU eviction for the GIMO Inference Engine.

Keeps loaded model sessions alive between requests so we avoid the expensive
model-load penalty on every call.  Evicts least-recently-used sessions when
memory pressure is too high or the pool is full.

Typical usage::

    pool = SessionPool(max_sessions=4, max_memory_mb=12_000)
    handle = await pool.get_or_load(spec, device, adapter)
    outputs = await adapter.run(handle, inputs)
    # handle stays in pool until evicted
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..contracts import HardwareTarget, ModelSpec
from .base_adapter import RuntimeAdapter, SessionHandle

logger = logging.getLogger("gie.runtime.pool")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class PoolMetrics:
    """Cumulative counters for the session pool."""
    hits: int = 0           # requests served from pool
    misses: int = 0         # sessions that had to be loaded from disk
    evictions: int = 0      # sessions evicted due to pressure
    load_errors: int = 0    # failed load attempts
    total_load_ms: float = 0.0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    @property
    def avg_load_ms(self) -> float:
        return self.total_load_ms / self.misses if self.misses else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "load_errors": self.load_errors,
            "hit_rate": round(self.hit_rate, 3),
            "avg_load_ms": round(self.avg_load_ms, 1),
        }


# ---------------------------------------------------------------------------
# Pool key
# ---------------------------------------------------------------------------

def _pool_key(model_id: str, device: HardwareTarget) -> str:
    return f"{model_id}::{device.value}"


# ---------------------------------------------------------------------------
# SessionPool
# ---------------------------------------------------------------------------

class SessionPool:
    """Thread-safe LRU pool of active inference sessions.

    Args:
        max_sessions:   Hard cap on simultaneous loaded sessions.
        max_memory_mb:  Soft cap on total session memory.  When exceeded,
                        the LRU session is evicted until we are under the cap.
        warmup_ids:     Model IDs to pre-load on startup (optional).
    """

    def __init__(
        self,
        max_sessions: int = 4,
        max_memory_mb: float = 8_000.0,
        warmup_ids: Optional[List[str]] = None,
    ) -> None:
        self._max_sessions = max_sessions
        self._max_memory_mb = max_memory_mb
        self._warmup_ids: List[str] = warmup_ids or []

        # OrderedDict preserves insertion/update order → LRU via move_to_end.
        # Key: pool_key  →  Value: SessionHandle
        self._sessions: OrderedDict[str, SessionHandle] = OrderedDict()
        # Adapter reference kept per key so we can call unload().
        self._adapters: Dict[str, RuntimeAdapter] = {}

        self._lock = asyncio.Lock()
        self.metrics = PoolMetrics()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_or_load(
        self,
        spec: ModelSpec,
        device: HardwareTarget,
        adapter: RuntimeAdapter,
    ) -> SessionHandle:
        """Return a cached session or load one, evicting if necessary.

        This is the primary entry point for the engine — it guarantees that a
        valid, ready-to-use session is returned (or raises on irrecoverable error).
        """
        key = _pool_key(spec.model_id, device)

        async with self._lock:
            if key in self._sessions:
                # Cache hit — bump to most-recently-used position.
                self._sessions.move_to_end(key)
                self._sessions[key].last_used = time.monotonic()
                self.metrics.hits += 1
                logger.debug("Pool hit: %s", key)
                return self._sessions[key]

            # Cache miss — load the model.
            self.metrics.misses += 1
            logger.debug("Pool miss: %s — loading", key)
            t0 = time.monotonic()
            try:
                handle = await adapter.load_model(spec, device)
            except Exception as exc:
                self.metrics.load_errors += 1
                logger.error("Failed to load %s: %s", key, exc)
                raise

            elapsed_ms = (time.monotonic() - t0) * 1000
            self.metrics.total_load_ms += elapsed_ms

            # Evict sessions to make room before adding the new one.
            await self._evict_if_needed(handle.memory_mb)

            self._sessions[key] = handle
            self._adapters[key] = adapter
            return handle

    async def evict(self, model_id: str, device: Optional[HardwareTarget] = None) -> None:
        """Explicitly evict a specific model from the pool."""
        async with self._lock:
            if device is not None:
                key = _pool_key(model_id, device)
                await self._evict_key(key)
            else:
                keys_to_evict = [k for k in self._sessions if k.startswith(f"{model_id}::")]
                for key in keys_to_evict:
                    await self._evict_key(key)

    async def evict_all(self) -> None:
        """Unload all sessions (called on engine shutdown)."""
        async with self._lock:
            for key in list(self._sessions):
                await self._evict_key(key)

    def is_loaded(self, model_id: str, device: HardwareTarget) -> bool:
        return _pool_key(model_id, device) in self._sessions

    def loaded_models(self) -> List[Dict[str, Any]]:
        """Return a snapshot of currently loaded sessions for monitoring."""
        return [
            {
                "key": k,
                "model_id": v.model_id,
                "device": v.hardware_target.value,
                "ep": v.execution_provider.value,
                "memory_mb": v.memory_mb,
                "last_used_age_s": round(time.monotonic() - v.last_used, 1),
            }
            for k, v in self._sessions.items()
        ]

    def total_memory_mb(self) -> float:
        return sum(s.memory_mb for s in self._sessions.values())

    def session_count(self) -> int:
        return len(self._sessions)

    # ------------------------------------------------------------------
    # Warmup
    # ------------------------------------------------------------------

    async def warmup(
        self,
        specs: List[ModelSpec],
        device: HardwareTarget,
        adapter: RuntimeAdapter,
    ) -> None:
        """Pre-load frequently used models into the pool.

        Only loads models whose ``model_id`` appears in ``self._warmup_ids``.
        Silently skips any that fail (warmup failures are non-fatal).
        """
        warm_set = set(self._warmup_ids)
        for spec in specs:
            if spec.model_id not in warm_set:
                continue
            try:
                logger.info("Warming up session for %s on %s", spec.model_id, device.value)
                await self.get_or_load(spec, device, adapter)
            except Exception as exc:
                logger.warning("Warmup failed for %s: %s", spec.model_id, exc)

    # ------------------------------------------------------------------
    # Internal eviction logic
    # ------------------------------------------------------------------

    async def _evict_if_needed(self, incoming_mb: float) -> None:
        """Evict LRU entries until we have room for *incoming_mb* bytes."""
        # Evict if we exceed session count cap.
        while len(self._sessions) >= self._max_sessions:
            await self._evict_lru()

        # Evict if we would exceed memory cap.
        while (
            self._sessions
            and self.total_memory_mb() + incoming_mb > self._max_memory_mb
        ):
            await self._evict_lru()

    async def _evict_lru(self) -> None:
        """Evict the least-recently-used session (first in OrderedDict)."""
        if not self._sessions:
            return
        lru_key, _ = next(iter(self._sessions.items()))
        await self._evict_key(lru_key)

    async def _evict_key(self, key: str) -> None:
        """Unload and remove a specific session by key."""
        handle = self._sessions.pop(key, None)
        adapter = self._adapters.pop(key, None)
        if handle is None:
            return
        try:
            if adapter is not None:
                await adapter.unload(handle)
        except Exception as exc:
            logger.warning("Error unloading session %s: %s", key, exc)
        self.metrics.evictions += 1
        logger.info("Evicted session %s (memory freed: %.0f MB)", key, handle.memory_mb)
