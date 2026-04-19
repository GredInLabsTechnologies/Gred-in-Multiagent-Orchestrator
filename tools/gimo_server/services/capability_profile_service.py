"""Capability Profile Service — GICS-backed per-model-per-task_type specialization tracking.

Builds emergent specialization profiles: the system learns WHAT each model is
good at (and bad at) from accumulated execution history, without any human
configuration. This enables agents to self-assess before executing and make
intelligent strategy decisions.

Keys in GICS:
    ops:capability:{provider}:{model}:{task_type}  →  task-specific scores
    ops:capability_index:{provider}:{model}        →  list of known task_types
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.services.capability_profile")


@dataclass
class TaskCapability:
    """Capability snapshot for a single model + task_type combination."""
    task_type: str
    samples: int = 0
    successes: int = 0
    failures: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    failure_streak: int = 0
    last_failure_reason: str = ""
    updated_at: int = 0


@dataclass
class ModelProfile:
    """Full capability profile for a model across all observed task types."""
    provider_type: str
    model_id: str
    strengths: List[TaskCapability] = field(default_factory=list)  # success_rate >= 0.7
    weaknesses: List[TaskCapability] = field(default_factory=list)  # success_rate < 0.5
    neutral: List[TaskCapability] = field(default_factory=list)    # 0.5 <= rate < 0.7
    total_samples: int = 0
    overall_success_rate: float = 0.0


class CapabilityProfileService:
    """Builds and queries per-model-per-task_type capability profiles from GICS."""

    @staticmethod
    def _task_key(provider_type: str, model_id: str, task_type: str) -> str:
        p = provider_type.strip().lower().replace(" ", "_")
        m = model_id.strip().lower().replace(" ", "_")
        t = task_type.strip().lower().replace(" ", "_")
        return f"ops:capability:{p}:{m}:{t}"

    @staticmethod
    def _index_key(provider_type: str, model_id: str) -> str:
        p = provider_type.strip().lower().replace(" ", "_")
        m = model_id.strip().lower().replace(" ", "_")
        return f"ops:capability_index:{p}:{m}"

    @classmethod
    def _gics(cls):
        from .ops import OpsService
        return OpsService._gics

    @classmethod
    def record_task_outcome(
        cls,
        *,
        provider_type: str,
        model_id: str,
        task_type: str,
        success: bool,
        latency_ms: Optional[float] = None,
        cost_usd: Optional[float] = None,
        failure_reason: str = "",
    ) -> Optional[TaskCapability]:
        """Record outcome for a specific model+task_type combination.
        Returns the updated TaskCapability or None if GICS unavailable.
        """
        gics = cls._gics()
        if not gics:
            return None

        key = cls._task_key(provider_type, model_id, task_type)
        try:
            existing = gics.get(key)
            fields = dict((existing or {}).get("fields") or {})
        except Exception:
            fields = {}

        samples = int(fields.get("samples", 0)) + 1
        successes = int(fields.get("successes", 0)) + (1 if success else 0)
        failures = int(fields.get("failures", 0)) + (0 if success else 1)
        streak = 0 if success else int(fields.get("failure_streak", 0)) + 1

        prev_lat = float(fields.get("avg_latency_ms", 0.0))
        prev_cost = float(fields.get("avg_cost_usd", 0.0))
        new_lat = float(latency_ms or 0.0)
        new_cost = float(cost_usd or 0.0)
        avg_lat = ((prev_lat * (samples - 1)) + new_lat) / max(1, samples)
        avg_cost = ((prev_cost * (samples - 1)) + new_cost) / max(1, samples)

        updated = {
            "task_type": task_type,
            "provider_type": provider_type,
            "model_id": model_id,
            "samples": samples,
            "successes": successes,
            "failures": failures,
            "success_rate": successes / max(1, samples),
            "avg_latency_ms": avg_lat,
            "avg_cost_usd": avg_cost,
            "failure_streak": streak,
            "last_failure_reason": failure_reason if not success else fields.get("last_failure_reason", ""),
            "updated_at": int(time.time()),
        }

        try:
            gics.put(key, updated)
            # Update the task_type index for this model
            cls._add_to_index(provider_type, model_id, task_type)
        except Exception as exc:
            logger.warning("GICS capability write failed: %s", exc)
            return None

        return TaskCapability(**{k: updated[k] for k in TaskCapability.__dataclass_fields__})

    @classmethod
    def _add_to_index(cls, provider_type: str, model_id: str, task_type: str) -> None:
        gics = cls._gics()
        if not gics:
            return
        idx_key = cls._index_key(provider_type, model_id)
        try:
            existing = gics.get(idx_key)
            fields = dict((existing or {}).get("fields") or {})
            known = list(fields.get("task_types", []))
            if task_type not in known:
                known.append(task_type)
                gics.put(idx_key, {"task_types": known, "updated_at": int(time.time())})
        except Exception:
            try:
                gics.put(idx_key, {"task_types": [task_type], "updated_at": int(time.time())})
            except Exception:
                pass

    @classmethod
    def get_capability(
        cls,
        *,
        provider_type: str,
        model_id: str,
        task_type: str,
    ) -> Optional[TaskCapability]:
        """Get the capability profile for a model on a specific task type."""
        gics = cls._gics()
        if not gics:
            return None
        key = cls._task_key(provider_type, model_id, task_type)
        try:
            result = gics.get(key)
            if not result or "fields" not in result:
                return None
            f = result["fields"]
            return TaskCapability(**{k: f[k] for k in TaskCapability.__dataclass_fields__ if k in f})
        except Exception:
            return None

    @classmethod
    def get_full_profile(cls, *, provider_type: str, model_id: str) -> ModelProfile:
        """Build the complete capability profile for a model across all task types."""
        gics = cls._gics()
        profile = ModelProfile(provider_type=provider_type, model_id=model_id)
        if not gics:
            return profile

        # Get known task types from index
        idx_key = cls._index_key(provider_type, model_id)
        try:
            idx = gics.get(idx_key)
            task_types = list((idx or {}).get("fields", {}).get("task_types", []))
        except Exception:
            return profile

        total_samples = 0
        total_successes = 0
        for tt in task_types:
            cap = cls.get_capability(provider_type=provider_type, model_id=model_id, task_type=tt)
            if not cap:
                continue
            total_samples += cap.samples
            total_successes += cap.successes
            if cap.success_rate >= 0.7:
                profile.strengths.append(cap)
            elif cap.success_rate < 0.5:
                profile.weaknesses.append(cap)
            else:
                profile.neutral.append(cap)

        profile.total_samples = total_samples
        profile.overall_success_rate = total_successes / max(1, total_samples)
        # Sort by success_rate descending for strengths, ascending for weaknesses
        profile.strengths.sort(key=lambda c: c.success_rate, reverse=True)
        profile.weaknesses.sort(key=lambda c: c.success_rate)
        return profile

    @classmethod
    def recommend_model_for_task(
        cls,
        *,
        task_type: str,
        max_tier: int = 5,
        min_samples: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """Given a task_type, find the best-performing model from historical data.
        Returns {"model_id", "provider_type", "success_rate", "samples"} or None.
        """
        gics = cls._gics()
        if not gics:
            return None
        try:
            from .model_inventory_service import ModelInventoryService
            models = ModelInventoryService.get_available_models()
        except Exception:
            return None

        best = None
        best_rate = -1.0
        for m in models:
            if m.quality_tier > max_tier:
                continue
            cap = cls.get_capability(
                provider_type=m.provider_type, model_id=m.model_id, task_type=task_type,
            )
            if not cap or cap.samples < min_samples:
                continue
            if cap.success_rate > best_rate:
                best_rate = cap.success_rate
                best = {
                    "model_id": m.model_id,
                    "provider_type": m.provider_type,
                    "success_rate": cap.success_rate,
                    "samples": cap.samples,
                    "quality_tier": m.quality_tier,
                }
        return best
