"""
Duration Telemetry Service — Phase 1 of GAEP.

Captures execution duration metrics for operations to train the adaptive timeout predictor.
Stores data in GICS with schema: ops:duration:{operation}:{timestamp_ms}
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.services.timeout.duration_telemetry")


class DurationTelemetryService:
    """Captura métricas de duración para operaciones y las almacena en GICS."""

    # Singleton GICS instance (injected from FastAPI app state)
    _gics = None

    @classmethod
    def set_gics(cls, gics) -> None:
        """Inject GICS service instance."""
        cls._gics = gics

    @classmethod
    def _get_gics(cls):
        """Get GICS instance, raising if not initialized."""
        if cls._gics is None:
            raise RuntimeError("DurationTelemetryService: GICS not initialized. Call set_gics() first.")
        return cls._gics

    @classmethod
    def record_operation_duration(
        cls,
        operation: str,
        duration: float,
        context: Dict[str, Any],
        success: bool,
    ) -> Optional[str]:
        """
        Almacena métricas de duración en GICS.

        Args:
            operation: Operation type (e.g., "plan", "run", "merge")
            duration: Duration in seconds (float)
            context: Contextual metadata (model, prompt_length, file_count, etc.)
            success: Whether operation succeeded

        Returns:
            GICS key of stored record, or None if storage failed

        Schema:
            Key: ops:duration:{operation}:{timestamp_ms}
            Fields: {
                "operation": str,
                "duration_s": float,
                "success": bool,
                "context": dict,
                "timestamp": int (unix seconds)
            }
        """
        try:
            gics = cls._get_gics()
            timestamp_ms = int(time.time() * 1000)
            key = f"ops:duration:{operation}:{timestamp_ms}"

            fields = {
                "operation": operation,
                "duration_s": round(duration, 3),
                "success": success,
                "context": context,
                "timestamp": int(time.time()),
            }

            gics.put(key, fields)
            logger.info(
                "Duration recorded: %s completed in %.2fs (success=%s)",
                operation, duration, success
            )
            return key

        except Exception as exc:
            logger.error("Failed to record duration for %s: %s", operation, exc, exc_info=True)
            return None

    @classmethod
    def get_historical_durations(
        cls,
        operation: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[float]:
        """
        Recupera duraciones históricas similares de GICS para predicción.

        Args:
            operation: Operation type to filter by
            context: Optional context to match similar operations
            limit: Maximum number of records to retrieve

        Returns:
            List of durations in seconds (most recent first)

        Filtering strategy:
            1. Scan all records for this operation type
            2. Filter by contextual similarity (if context provided)
            3. Return up to `limit` most recent durations
        """
        try:
            gics = cls._get_gics()
            prefix = f"ops:duration:{operation}:"

            # Scan all records for this operation
            records = gics.scan(prefix=prefix)

            if not records:
                logger.debug("No historical durations found for operation: %s", operation)
                return []

            # Extract durations from fields
            durations = []
            for record in records:
                fields = record.get("fields") or {}

                # Only include successful operations for prediction
                if not fields.get("success", False):
                    continue

                duration = fields.get("duration_s")
                if duration is not None:
                    # Optional: filter by context similarity
                    if context:
                        record_context = fields.get("context", {})
                        if cls._is_similar_context(context, record_context):
                            durations.append(float(duration))
                    else:
                        durations.append(float(duration))

            # Sort by timestamp (most recent first) and limit
            # Note: records from scan() are already sorted by key (timestamp in key)
            durations = durations[:limit]

            logger.debug(
                "Retrieved %d historical durations for %s (limit=%d)",
                len(durations), operation, limit
            )
            return durations

        except Exception as exc:
            logger.error(
                "Failed to retrieve historical durations for %s: %s",
                operation, exc, exc_info=True
            )
            return []

    @staticmethod
    def _is_similar_context(target: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
        """
        Determina si dos contextos son similares (para filtrado de duraciones).

        Similarity criteria:
            - Same model (exact match)
            - Similar prompt length (within 50%)
            - Similar file count (within 50%)
            - Same provider (exact match)

        Returns:
            True if contexts are similar enough to be compared
        """
        # Model match (exact)
        if target.get("model") != candidate.get("model"):
            return False

        # Provider match (exact)
        if "provider" in target and "provider" in candidate:
            if target["provider"] != candidate["provider"]:
                return False

        # Prompt length similarity (within 50%)
        if "prompt_length" in target and "prompt_length" in candidate:
            target_len = target["prompt_length"]
            candidate_len = candidate["prompt_length"]
            if target_len > 0:
                ratio = candidate_len / target_len
                if ratio < 0.5 or ratio > 2.0:
                    return False

        # File count similarity (within 50%)
        if "file_count" in target and "file_count" in candidate:
            target_count = target["file_count"]
            candidate_count = candidate["file_count"]
            if target_count > 0:
                ratio = candidate_count / target_count
                if ratio < 0.5 or ratio > 2.0:
                    return False

        return True

    @classmethod
    def get_stats_for_operation(cls, operation: str) -> Dict[str, Any]:
        """
        Obtiene estadísticas agregadas para una operación.

        Returns:
            {
                "operation": str,
                "total_samples": int,
                "success_rate": float,
                "avg_duration_s": float,
                "p50_duration_s": float,
                "p95_duration_s": float,
                "max_duration_s": float,
            }
        """
        try:
            gics = cls._get_gics()
            prefix = f"ops:duration:{operation}:"
            records = gics.scan(prefix=prefix)

            if not records:
                return {
                    "operation": operation,
                    "total_samples": 0,
                    "success_rate": 0.0,
                    "avg_duration_s": 0.0,
                    "p50_duration_s": 0.0,
                    "p95_duration_s": 0.0,
                    "max_duration_s": 0.0,
                }

            successes = 0
            durations = []

            for record in records:
                fields = record.get("fields") or {}
                if fields.get("success", False):
                    successes += 1
                duration = fields.get("duration_s")
                if duration is not None:
                    durations.append(float(duration))

            total_samples = len(records)
            success_rate = successes / total_samples if total_samples > 0 else 0.0

            if not durations:
                return {
                    "operation": operation,
                    "total_samples": total_samples,
                    "success_rate": success_rate,
                    "avg_duration_s": 0.0,
                    "p50_duration_s": 0.0,
                    "p95_duration_s": 0.0,
                    "max_duration_s": 0.0,
                }

            sorted_durations = sorted(durations)
            avg_duration = sum(durations) / len(durations)
            p50_index = int(len(sorted_durations) * 0.5)
            p95_index = int(len(sorted_durations) * 0.95)

            return {
                "operation": operation,
                "total_samples": total_samples,
                "success_rate": round(success_rate, 3),
                "avg_duration_s": round(avg_duration, 2),
                "p50_duration_s": round(sorted_durations[p50_index], 2),
                "p95_duration_s": round(sorted_durations[p95_index], 2),
                "max_duration_s": round(max(durations), 2),
            }

        except Exception as exc:
            logger.error("Failed to get stats for %s: %s", operation, exc, exc_info=True)
            return {
                "operation": operation,
                "total_samples": 0,
                "success_rate": 0.0,
                "avg_duration_s": 0.0,
                "p50_duration_s": 0.0,
                "p95_duration_s": 0.0,
                "max_duration_s": 0.0,
            }
