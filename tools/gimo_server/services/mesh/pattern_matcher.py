from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional

from ...models.mesh import TaskFingerprint
from ..gics_service import GicsService

logger = logging.getLogger("orchestrator.mesh.pattern_matcher")


class PatternMatcher:
    """Thompson Sampling model selector backed by GICS task pattern data."""

    def __init__(self, gics: GicsService) -> None:
        self._gics = gics

    def select_model(
        self,
        fingerprint: TaskFingerprint,
        available_models: List[str],
    ) -> str:
        """Select best model for a task using Thompson Sampling.

        For each model, query GICS for success/failure counts on the
        fingerprint's action_class.  Sample from Beta(alpha, beta) and
        return the model with the highest sample.
        """
        if not available_models:
            raise ValueError("No available models for selection")

        if len(available_models) == 1:
            return available_models[0]

        best_model = available_models[0]
        best_sample = -1.0

        for model_id in available_models:
            alpha, beta = self._get_prior(fingerprint.action_class, model_id)
            sample = random.betavariate(alpha, beta)
            logger.debug(
                "Thompson sample for %s on %s: Beta(%.1f, %.1f) = %.4f",
                model_id, fingerprint.action_class, alpha, beta, sample,
            )
            if sample > best_sample:
                best_sample = sample
                best_model = model_id

        logger.info(
            "Selected %s for action_class=%s (sample=%.4f)",
            best_model, fingerprint.action_class, best_sample,
        )
        return best_model

    def _get_prior(self, action_class: str, model_id: str) -> tuple[float, float]:
        """Get Beta distribution parameters from GICS task pattern data.

        Returns (alpha, beta) where alpha = successes + 1, beta = failures + 1.
        Uniform prior Beta(1, 1) when no data exists.
        """
        result = self._gics.query_task_pattern(
            task_type=action_class,
            model_id=model_id,
        )
        data = result.get("data")
        if data is None:
            return 1.0, 1.0

        successes = float(data.get("successes", 0) or 0)
        failures = float(data.get("failures", 0) or 0)
        return successes + 1.0, failures + 1.0

    def record_outcome(
        self,
        fingerprint: TaskFingerprint,
        model_id: str,
        provider_type: str,
        success: bool,
        latency_ms: float = 0.0,
        cost_usd: float = 0.0,
    ) -> None:
        """Record task outcome in GICS for future Thompson Sampling."""
        self._gics._record_task_pattern(
            provider_type=provider_type,
            model_id=model_id,
            task_type=fingerprint.action_class,
            success=success,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )
        logger.info(
            "Recorded outcome for %s on %s: success=%s latency=%.0fms",
            model_id, fingerprint.action_class, success, latency_ms,
        )

    def find_similar_patterns(
        self,
        fingerprint: TaskFingerprint,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Find task patterns similar to the given fingerprint.

        Uses simple feature overlap scoring: action_class match,
        domain_hints Jaccard similarity.
        """
        all_patterns = self._gics.get_task_patterns()
        scored: List[tuple[float, Dict[str, Any]]] = []

        fp_hints = set(fingerprint.domain_hints)

        for pattern in all_patterns:
            task_type = pattern.get("task_type", "")
            score = 0.0

            # Exact action_class match
            if task_type == fingerprint.action_class:
                score += 1.0
            # Partial match — shared prefix or substring
            elif fingerprint.action_class in task_type or task_type in fingerprint.action_class:
                score += 0.5

            # Domain hints overlap (Jaccard)
            if fp_hints:
                pattern_hints: set[str] = set()
                for model_data in pattern.get("models", []):
                    # Check if model dealt with similar domains
                    model_task = str(model_data.get("task_type", ""))
                    pattern_hints.update(model_task.split("_"))
                if pattern_hints:
                    intersection = fp_hints & pattern_hints
                    union = fp_hints | pattern_hints
                    score += len(intersection) / len(union) if union else 0.0

            scored.append((score, pattern))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:top_k]]
