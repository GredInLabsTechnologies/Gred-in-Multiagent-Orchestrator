"""Task Router — maps semantic task types to the optimal hardware target.

Given an InferenceRequest, the TaskRouter decides:
1. Which hardware device to use (GPU/NPU/CPU)
2. Which model to select (if not explicitly specified)
3. What shard strategy is needed

Decision factors (in priority order):
1. Task affinity (embedding → NPU, reasoning → GPU, …)
2. Available memory on the preferred device
3. Current device utilization %
4. Device temperature
5. EWMA latency history per device
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Dict, List, Optional

from ..contracts import (
    DeviceCapability,
    HardwareTarget,
    InferenceRequest,
    ModelSpec,
    ShardStrategy,
    TaskSemantic,
)

logger = logging.getLogger("gie.router.task")

# ---------------------------------------------------------------------------
# Task → Hardware affinity table (from the plan)
# ---------------------------------------------------------------------------

TASK_AFFINITY: Dict[TaskSemantic, List[HardwareTarget]] = {
    TaskSemantic.EMBEDDING:       [HardwareTarget.NPU, HardwareTarget.GPU, HardwareTarget.CPU],
    TaskSemantic.VISION:          [HardwareTarget.NPU, HardwareTarget.GPU, HardwareTarget.CPU],
    TaskSemantic.SPEECH:          [HardwareTarget.NPU, HardwareTarget.CPU, HardwareTarget.GPU],
    TaskSemantic.CLASSIFICATION:  [HardwareTarget.NPU, HardwareTarget.CPU, HardwareTarget.GPU],
    TaskSemantic.RERANKING:       [HardwareTarget.NPU, HardwareTarget.CPU, HardwareTarget.GPU],
    TaskSemantic.REASONING:       [HardwareTarget.GPU, HardwareTarget.CPU, HardwareTarget.NPU],
    TaskSemantic.CODE_GENERATION: [HardwareTarget.GPU, HardwareTarget.CPU, HardwareTarget.NPU],
    TaskSemantic.DIFFUSION:       [HardwareTarget.GPU, HardwareTarget.NPU, HardwareTarget.CPU],
    TaskSemantic.SUMMARIZATION:   [HardwareTarget.GPU, HardwareTarget.NPU, HardwareTarget.CPU],
    TaskSemantic.TRANSLATION:     [HardwareTarget.GPU, HardwareTarget.NPU, HardwareTarget.CPU],
    TaskSemantic.GENERAL:         [HardwareTarget.GPU, HardwareTarget.CPU, HardwareTarget.NPU],
}

# Temperature thresholds (°C) — above WARN we deprioritise, above CRITICAL we skip.
_TEMP_WARN     = 80.0
_TEMP_CRITICAL = 90.0

# Utilization threshold — above this we deprioritise the device.
_UTIL_HIGH = 85.0


@dataclass
class RoutingDecision:
    """Result of the routing algorithm."""
    target_device: HardwareTarget
    selected_model: Optional[ModelSpec]
    shard_strategy: ShardStrategy = ShardStrategy.NONE
    fallback_device: Optional[HardwareTarget] = None
    rationale: str = ""
    score: float = 0.0


@dataclass
class _DeviceScore:
    device: DeviceCapability
    affinity_rank: int          # lower = more preferred for this task
    score: float = 0.0


class TaskRouter:
    """Routes inference requests to the optimal hardware device.

    Args:
        devices:       Live device list from DeviceDetector (refreshed externally).
        latency_ewma:  Per-device EWMA latency dict; updated by the engine.
    """

    def __init__(
        self,
        devices: Optional[List[DeviceCapability]] = None,
        latency_ewma: Optional[Dict[str, float]] = None,
    ) -> None:
        self._devices: List[DeviceCapability] = devices or []
        # EWMA latency in ms per device_type string.
        self._latency_ewma: Dict[str, float] = latency_ewma or {}

    def update_devices(self, devices: List[DeviceCapability]) -> None:
        self._devices = devices

    def update_latency(self, device_type: str, latency_ms: float, alpha: float = 0.2) -> None:
        """Update exponentially weighted moving average latency."""
        prev = self._latency_ewma.get(device_type, latency_ms)
        self._latency_ewma[device_type] = (1 - alpha) * prev + alpha * latency_ms

    def route(
        self,
        request: InferenceRequest,
        model: Optional[ModelSpec] = None,
    ) -> RoutingDecision:
        """Return the best routing decision for *request*.

        If ``request.target_hardware`` is not AUTO, it takes precedence
        (after checking that the device actually has capacity).
        """
        if not self._devices:
            return RoutingDecision(
                target_device=HardwareTarget.CPU,
                selected_model=model,
                rationale="No devices detected; defaulting to CPU",
            )

        # Explicit target requested.
        if request.target_hardware != HardwareTarget.AUTO:
            return self._route_explicit(request, model)

        return self._route_auto(request, model)

    # ------------------------------------------------------------------
    # Internal routing logic
    # ------------------------------------------------------------------

    def _route_explicit(
        self,
        request: InferenceRequest,
        model: Optional[ModelSpec],
    ) -> RoutingDecision:
        target = request.target_hardware
        device = next((d for d in self._devices if d.device_type == target), None)
        if device is None:
            # Target device not available → fall back.
            logger.warning(
                "Requested device %s not available; falling back to AUTO routing",
                target.value,
            )
            return self._route_auto(request, model)

        if device.temperature_celsius > _TEMP_CRITICAL:
            logger.warning(
                "Device %s is at critical temperature (%.0f°C); routing elsewhere",
                target.value,
                device.temperature_celsius,
            )
            return self._route_auto(request, model)

        return RoutingDecision(
            target_device=target,
            selected_model=model,
            rationale=f"Explicit target: {target.value}",
            score=1.0,
        )

    def _route_auto(
        self,
        request: InferenceRequest,
        model: Optional[ModelSpec],
    ) -> RoutingDecision:
        affinity = TASK_AFFINITY.get(request.task, TASK_AFFINITY[TaskSemantic.GENERAL])

        # Build scores for each available device (skip devices at critical temp).
        candidates: List[_DeviceScore] = []
        for dev in self._devices:
            if dev.temperature_celsius >= _TEMP_CRITICAL:
                logger.warning(
                    "Excluding %s from auto-routing (temp=%.0f°C ≥ critical %.0f°C)",
                    dev.device_type.value,
                    dev.temperature_celsius,
                    _TEMP_CRITICAL,
                )
                continue
            try:
                rank = affinity.index(dev.device_type)
            except ValueError:
                rank = len(affinity)  # device not in affinity → lowest priority
            candidates.append(_DeviceScore(device=dev, affinity_rank=rank))

        # Sort by affinity rank first, then compute composite score.
        candidates.sort(key=lambda c: c.affinity_rank)
        for cand in candidates:
            cand.score = self._score_device(cand.device, cand.affinity_rank, model)

        # Re-sort by composite score (higher = better).
        candidates.sort(key=lambda c: c.score, reverse=True)

        if not candidates:
            return RoutingDecision(
                target_device=HardwareTarget.CPU,
                selected_model=model,
                rationale="No candidates; defaulting to CPU",
            )

        best = candidates[0]
        fallback_device = candidates[1].device.device_type if len(candidates) > 1 else None

        rationale = (
            f"Task={request.task.value}, best device={best.device.device_type.value} "
            f"(score={best.score:.2f}, affinity_rank={best.affinity_rank})"
        )

        logger.info("TaskRouter: %s → %s", request.task.value, best.device.device_type.value)

        return RoutingDecision(
            target_device=best.device.device_type,
            selected_model=model,
            fallback_device=fallback_device,
            rationale=rationale,
            score=best.score,
        )

    def _score_device(
        self,
        device: DeviceCapability,
        affinity_rank: int,
        model: Optional[ModelSpec],
    ) -> float:
        """Compute a composite score for *device*.  Higher = better.

        Components:
        - Affinity: max_rank − rank  (0 = best affinity, penalised linearly)
        - Memory:   free_memory / total_memory
        - Utilization: 1 - utilization_pct / 100
        - Temperature: penalty above warn threshold
        - EWMA latency: lower is better (normalised to [0, 1])
        """
        max_rank = 3  # we have 3 entries in each affinity list
        affinity_score = (max_rank - affinity_rank) / max_rank  # [0, 1]

        memory_score = (
            device.free_memory_gb / device.total_memory_gb
            if device.total_memory_gb > 0 else 0.5
        )

        util_score = 1.0 - (device.utilization_percent / 100.0)

        temp = device.temperature_celsius
        if temp >= _TEMP_CRITICAL:
            temp_penalty = 1.0    # effectively excludes device
        elif temp >= _TEMP_WARN:
            temp_penalty = 0.5
        else:
            temp_penalty = 0.0

        latency_ms = self._latency_ewma.get(device.device_type.value, 0.0)
        # Normalise against a 5-second reference latency.
        latency_score = max(0.0, 1.0 - latency_ms / 5000.0)

        score = (
            0.40 * affinity_score
            + 0.25 * memory_score
            + 0.15 * util_score
            + 0.10 * latency_score
            - 0.10 * temp_penalty
        )
        return round(max(0.0, score), 4)
