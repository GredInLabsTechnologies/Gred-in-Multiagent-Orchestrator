"""Model Selector — choose the best local model for a given task.

Given a task semantic and a list of candidate models, selects the model that:
1. Supports the requested task
2. Fits in the available device memory
3. Has the highest quality tier
4. Minimises reload penalty (prefer already-loaded sessions)

This complements ModelInventoryService by adding hardware-awareness.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Set

from ..contracts import (
    DeviceCapability,
    HardwareTarget,
    ModelSpec,
    TaskSemantic,
)

logger = logging.getLogger("gie.router.model_selector")


@dataclass
class SelectionResult:
    """Result of model selection."""
    model: Optional[ModelSpec]
    reason: str
    fits_in_memory: bool = False
    already_loaded: bool = False


class ModelSelector:
    """Selects the best model for a (task, device) combination.

    Args:
        is_loaded_fn:   Callback that checks if a model is currently in the
                        session pool.  Signature: (model_id, device) → bool.
        fits_fn:        Callback that checks if a model fits in device memory.
                        Signature: (model, devices) → bool.
    """

    def __init__(
        self,
        is_loaded_fn: Optional[Callable[[str, HardwareTarget], bool]] = None,
        fits_fn: Optional[Callable[[ModelSpec, List[DeviceCapability]], bool]] = None,
    ) -> None:
        self._is_loaded = is_loaded_fn or (lambda mid, dev: False)
        self._fits = fits_fn or (lambda m, _devs: True)

    def select(
        self,
        task: TaskSemantic,
        candidates: List[ModelSpec],
        devices: List[DeviceCapability],
        preferred_device: HardwareTarget = HardwareTarget.AUTO,
        *,
        quality_tiers: Optional[List[str]] = None,
    ) -> SelectionResult:
        """Select the best model from *candidates* for *task* on *devices*.

        Selection order (descending priority):
        1. Model supports *task*
        2. Model is already loaded in the session pool for *preferred_device*
        3. Model fits in *preferred_device* memory
        4. Quality tier (higher = better) — based on quality_tiers ordering
        5. Smallest model that meets the quality bar (for latency)

        Returns SelectionResult with the chosen model (or None if no candidate fits).
        """
        if not candidates:
            return SelectionResult(model=None, reason="No candidate models provided")

        # Filter: must support the requested task.
        task_capable = [
            m for m in candidates
            if not m.supported_tasks or task in m.supported_tasks
        ]
        if not task_capable:
            return SelectionResult(
                model=None,
                reason=f"No model supports task '{task.value}'. "
                       f"Available tasks: {self._all_tasks(candidates)}",
            )

        # Filter: must fit in memory.
        fitting = [m for m in task_capable if self._fits(m, devices)]
        if not fitting:
            # Return the smallest candidate with a "too large" warning.
            smallest = min(task_capable, key=lambda m: m.size_bytes)
            return SelectionResult(
                model=smallest,
                reason=f"No model fits in available device memory; "
                       f"returning smallest ({smallest.model_id}) which will require sharding",
                fits_in_memory=False,
                already_loaded=self._is_loaded(smallest.model_id, preferred_device),
            )

        # Score each fitting model.
        tiers = quality_tiers or []
        scored = sorted(
            fitting,
            key=lambda m: self._score(m, preferred_device, tiers),
            reverse=True,
        )
        best = scored[0]
        already = self._is_loaded(best.model_id, preferred_device)
        return SelectionResult(
            model=best,
            reason=f"Selected {best.model_id} (task={task.value}, "
                   f"already_loaded={already})",
            fits_in_memory=True,
            already_loaded=already,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _score(
        self,
        model: ModelSpec,
        device: HardwareTarget,
        quality_tiers: List[str],
    ) -> float:
        """Higher = better."""
        score = 0.0

        # +10 if already loaded (avoid expensive reload).
        if self._is_loaded(model.model_id, device):
            score += 10.0

        # Quality tier bonus: tier index in the ordered list.
        tier_name = model.metadata.get("quality_tier", "")
        if tier_name in quality_tiers:
            score += quality_tiers.index(tier_name)

        # Prefer smaller models (lower latency) as a tiebreaker.
        # Normalise against a 100 GB reference.
        size_gb = model.size_bytes / 1024**3
        score -= size_gb / 100.0

        return score

    @staticmethod
    def _all_tasks(models: List[ModelSpec]) -> Set[str]:
        tasks: Set[str] = set()
        for m in models:
            for t in m.supported_tasks:
                tasks.add(t.value)
        return tasks
