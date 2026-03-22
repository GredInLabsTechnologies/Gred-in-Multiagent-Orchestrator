"""GIMO Inference Engine Service — main orchestration singleton.

Exposes the unified API consumed by:
- routers/ops/inference_router.py (REST endpoints)
- services/engine_service.py (when routing to local models)

Lifecycle:
    engine = InferenceEngineService()
    await engine.initialize()
    result = await engine.infer(request)
    await engine.shutdown()

Inference flow:
    1. TaskRouter.route(request)       → device + fallback
    2. LoadBalancer.select(device)     → specific device instance
    3. ModelSelector.select(task, ...) → best model for this task
    4. MemoryManager.calculate_budget  → memory plan
    5. MemoryManager.plan_sharding     → shard strategy
    6. SessionPool.get_or_load         → load model if not cached
    7. HardwareScheduler.enqueue       → wait for execution slot
    8. RuntimeAdapter.run              → forward pass
    9. Release ticket, record metrics
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .compiler.model_cache import ModelCache
from .contracts import (
    DeviceCapability,
    HardwareTarget,
    InferenceRequest,
    InferenceResult,
    ModelSpec,
    ShardStrategy,
)
from .hardware.device_detector import get_devices
from .memory_manager import MemoryManager
from .metrics import InferenceMetrics
from .router.hardware_scheduler import HardwareScheduler
from .router.load_balancer import LoadBalancer
from .router.model_selector import ModelSelector
from .router.task_router import TaskRouter
from .runtime.onnx_adapter import OnnxAdapter
from .runtime.gguf_adapter import GgufAdapter
from .runtime.session_pool import SessionPool

logger = logging.getLogger("gie.engine")


class InferenceEngineService:
    """Singleton inference engine.

    Args:
        model_cache_dir:      Where compiled model artefacts are stored.
        model_cache_max_gb:   Max disk quota for compiled model cache.
        npu_enabled:          Allow NPU routing.
        max_oversized_ratio:  Load models up to this × device memory.
        session_pool_size:    Max concurrent loaded sessions.
        session_pool_mem_gb:  Max memory budget for session pool.
    """

    _instance: Optional["InferenceEngineService"] = None

    def __init__(
        self,
        *,
        model_cache_dir: Optional[Path] = None,
        model_cache_max_gb: float = 50.0,
        npu_enabled: bool = True,
        max_oversized_ratio: float = 3.0,
        session_pool_size: int = 4,
        session_pool_mem_gb: float = 12.0,
    ) -> None:
        self._cache = ModelCache(
            cache_dir=model_cache_dir,
            max_cache_gb=model_cache_max_gb,
        )
        self._npu_enabled = npu_enabled
        self._pool = SessionPool(
            max_sessions=session_pool_size,
            max_memory_mb=session_pool_mem_gb * 1024,
        )
        self._memory_manager = MemoryManager(
            disk_cache_dir=model_cache_dir,
            max_oversized_ratio=max_oversized_ratio,
        )
        self._onnx = OnnxAdapter()
        self._gguf = GgufAdapter()

        self._devices: List[DeviceCapability] = []
        self._task_router: Optional[TaskRouter] = None
        self._scheduler: Optional[HardwareScheduler] = None
        self._load_balancer: Optional[LoadBalancer] = None
        self._model_selector: Optional[ModelSelector] = None

        self._metrics = InferenceMetrics()
        self._initialized = False
        self._lock = asyncio.Lock()
        # In-memory model registry: model_id → ModelSpec.
        # Populated via register_model() or a future ModelInventoryService integration.
        self._registry: Dict[str, ModelSpec] = {}

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "InferenceEngineService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Detect hardware and initialise all sub-components."""
        async with self._lock:
            if self._initialized:
                return

            logger.info("Initializing GIMO Inference Engine…")
            self._devices = get_devices(force_refresh=True)

            if not self._npu_enabled:
                self._devices = [d for d in self._devices if d.device_type != HardwareTarget.NPU]

            self._task_router    = TaskRouter(devices=self._devices)
            self._scheduler      = HardwareScheduler(devices=self._devices)
            self._load_balancer  = LoadBalancer(devices=self._devices)
            self._model_selector = ModelSelector(
                is_loaded_fn=self._pool.is_loaded,
                fits_fn=self._memory_manager.fits_in_memory,
            )

            self._initialized = True
            logger.info(
                "GIE ready — devices: %s",
                [f"{d.device_type.value}:{d.device_name}" for d in self._devices],
            )

    async def shutdown(self) -> None:
        """Release all sessions and stop background tasks."""
        await self._pool.evict_all()
        self._initialized = False
        logger.info("GIE shut down")

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Execute a full inference request through the engine.

        This is the hot path — all heavy lifting is done here.
        """
        if not self._initialized:
            await self.initialize()

        t_start = time.monotonic()
        error: Optional[str] = None
        hardware_used = HardwareTarget.CPU
        device_name = "cpu"
        ep_name = "CPUExecutionProvider"
        tokens_generated = 0
        tps = 0.0
        mem_peak = 0.0

        try:
            # 1. Route the request.
            routing = self._task_router.route(request)  # type: ignore[union-attr]
            target_type = routing.target_device
            hardware_used = target_type

            # 2. Pick actual device instance via load balancer.
            device = self._load_balancer.select(target_type)  # type: ignore[union-attr]
            if device is None:
                device = next(
                    (d for d in self._devices if d.device_type == HardwareTarget.CPU),
                    None,
                )
            if device:
                device_name = device.device_name

            # 3. Determine the model to use.
            model_id = request.model_id
            model_spec = self._resolve_model(model_id)

            if model_spec is None:
                raise ValueError(f"Model '{model_id}' not found in registry")

            # 4. Compute memory budget and shard plan.
            budget = self._memory_manager.calculate_budget(model_spec, self._devices)
            shard_plan = self._memory_manager.plan_sharding(budget, model_spec, self._devices)

            if shard_plan.reject_reason:
                raise RuntimeError(
                    f"Cannot load model: {shard_plan.reject_reason}"
                )

            # 5. Load session (or get from pool).
            adapter = self._gguf if model_spec.format.value == "gguf" else self._onnx
            session = await self._pool.get_or_load(
                model_spec,
                device.device_type if device else HardwareTarget.CPU,
                adapter,
            )
            ep_name = session.execution_provider.value

            # 6. Enqueue with scheduler (wait for execution slot).
            ticket = await self._scheduler.enqueue(request, hardware_used)  # type: ignore[union-attr]
            await ticket.wait(timeout=request.timeout_seconds)

            try:
                # 7. Run inference.
                outputs = await adapter.run(session, request.inputs)
                tokens_generated = outputs.get("tokens_generated", 0)
                tps = outputs.get("tokens_per_second", 0.0)
            finally:
                self._scheduler.release(ticket)  # type: ignore[union-attr]

        except Exception as exc:
            error = str(exc)
            logger.error("Inference error for %s: %s", request.request_id, exc)
            outputs = {}

        latency_ms = (time.monotonic() - t_start) * 1000

        # Update metrics.
        self._metrics.record_request(
            request_id=request.request_id,
            model_id=request.model_id,
            task=request.task.value,
            device=hardware_used.value,
            latency_ms=latency_ms,
            tokens_generated=tokens_generated,
            tokens_per_second=tps,
            memory_peak_mb=mem_peak,
            error=error,
        )
        pool_m = self._pool.metrics
        self._metrics.update_pool_stats(pool_m.hits, pool_m.misses, pool_m.evictions)

        # Update latency EWMA in router.
        if self._task_router:
            self._task_router.update_latency(hardware_used.value, latency_ms)

        return InferenceResult(
            request_id=request.request_id,
            model_id=request.model_id,
            outputs=outputs,
            hardware_used=hardware_used,
            device_name=device_name,
            execution_provider=ep_name,
            latency_ms=round(latency_ms, 2),
            tokens_generated=tokens_generated,
            tokens_per_second=tps,
            memory_peak_mb=mem_peak,
            shard_strategy_used=ShardStrategy.NONE,
            error=error,
        )

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    async def load_model(self, model_id: str, target: HardwareTarget) -> bool:
        """Explicitly pre-load a model into the session pool."""
        spec = self._resolve_model(model_id)
        if spec is None:
            logger.warning("Cannot load unknown model: %s", model_id)
            return False
        adapter = self._gguf if spec.format.value == "gguf" else self._onnx
        try:
            await self._pool.get_or_load(spec, target, adapter)
            return True
        except Exception as exc:
            logger.error("Failed to load model %s: %s", model_id, exc)
            return False

    async def unload_model(self, model_id: str) -> bool:
        """Evict a model from the session pool."""
        await self._pool.evict(model_id)
        return True

    # ------------------------------------------------------------------
    # Status / introspection
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        return {
            "initialized": self._initialized,
            "devices": [
                {
                    "type": d.device_type.value,
                    "name": d.device_name,
                    "free_gb": d.free_memory_gb,
                    "total_gb": d.total_memory_gb,
                    "compute_tops": d.compute_tops,
                    "temp_c": d.temperature_celsius,
                    "utilization_pct": d.utilization_percent,
                }
                for d in self._devices
            ],
            "session_pool": {
                "count": self._pool.session_count(),
                "total_memory_mb": round(self._pool.total_memory_mb(), 1),
                "sessions": self._pool.loaded_models(),
                "metrics": self._pool.metrics.to_dict(),
            },
            "scheduler": self._scheduler.get_status() if self._scheduler else [],
        }

    def get_loaded_models(self) -> List[Dict[str, Any]]:
        return self._pool.loaded_models()

    def get_device_status(self) -> List[DeviceCapability]:
        return list(self._devices)

    def get_metrics(self) -> Dict[str, Any]:
        m = self._metrics.to_dict()
        if self._scheduler:
            m["queue_depths"] = {
                s["device"]: s["queued"]
                for s in self._scheduler.get_status()
            }
        return m

    # ------------------------------------------------------------------
    # Model registry
    # ------------------------------------------------------------------

    def register_model(self, spec: ModelSpec) -> None:
        """Register a model spec so it can be used for inference.

        Call this during application startup for each locally available model.
        When ModelInventoryService is integrated this will be replaced by a
        live lookup, but the registered specs will remain as a fallback.
        """
        self._registry[spec.model_id] = spec
        logger.info("Model registered: %s (%s, %.1fB params)", spec.model_id, spec.format.value, spec.param_count_b)

    def unregister_model(self, model_id: str) -> None:
        """Remove a model from the in-memory registry."""
        self._registry.pop(model_id, None)

    def list_registered_models(self) -> List[ModelSpec]:
        return list(self._registry.values())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_model(self, model_id: str) -> Optional[ModelSpec]:
        """Look up a model spec in the registry.

        Returns the registered ModelSpec or None if unknown.
        Future: query ModelInventoryService as primary, fall back to registry.
        """
        return self._registry.get(model_id)
