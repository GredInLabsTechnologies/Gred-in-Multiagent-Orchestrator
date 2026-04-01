"""
Checkpoint Service — Phase 5 of SEA (Sistema de Ejecución Adaptativa).

Manages checkpoints for resumable operations.
Operations can save intermediate state and be resumed later.
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.services.checkpoint")


class CheckpointService:
    """Gestiona checkpoints para operaciones resumibles."""

    # Singleton GICS instance (injected)
    _gics = None

    # TTL for checkpoints (24 hours)
    CHECKPOINT_TTL = 86400

    @classmethod
    def set_gics(cls, gics) -> None:
        """Inject GICS service instance."""
        cls._gics = gics

    @classmethod
    def _get_gics(cls):
        """Get GICS instance, raising if not initialized."""
        if cls._gics is None:
            raise RuntimeError("CheckpointService: GICS not initialized. Call set_gics() first.")
        return cls._gics

    @classmethod
    def save_checkpoint(
        cls,
        operation: str,
        operation_id: str,
        state: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Guarda checkpoint en GICS con TTL de 24h.

        Args:
            operation: Operation type (e.g., "plan", "run")
            operation_id: Unique operation ID (e.g., draft.id, run.id)
            state: Resumable state dictionary
            metadata: Optional additional metadata

        Returns:
            Checkpoint ID

        Schema:
            Key: ckpt:{operation}:{operation_id}:{checkpoint_id}
            Fields: {
                operation: str,
                operation_id: str,
                state: dict,
                metadata: dict,
                timestamp: int,
                resumable: bool,
                expires_at: int,
            }
        """
        try:
            gics = cls._get_gics()
            timestamp_ms = int(time.time() * 1000)
            checkpoint_id = f"ckpt_{timestamp_ms}"
            key = f"ckpt:{operation}:{operation_id}:{checkpoint_id}"

            fields = {
                "operation": operation,
                "operation_id": operation_id,
                "checkpoint_id": checkpoint_id,
                "state": state,
                "metadata": metadata or {},
                "timestamp": int(time.time()),
                "resumable": True,
                "expires_at": int(time.time()) + cls.CHECKPOINT_TTL,
            }

            gics.put(key, fields)

            logger.info(
                "Checkpoint saved: %s (operation=%s, id=%s)",
                checkpoint_id, operation, operation_id
            )

            return checkpoint_id

        except Exception as exc:
            logger.error(
                "Failed to save checkpoint for %s/%s: %s",
                operation, operation_id, exc, exc_info=True
            )
            return None

    @classmethod
    def get_checkpoint(cls, checkpoint_id: str) -> Optional[Dict[str, Any]]:
        """
        Recupera checkpoint de GICS por ID.

        Args:
            checkpoint_id: Checkpoint identifier (e.g., "ckpt_1735689650123")

        Returns:
            Checkpoint data dict, or None if not found
        """
        try:
            gics = cls._get_gics()

            # Scan for checkpoint with this ID
            # Pattern: ckpt:*:*:{checkpoint_id}
            prefix = "ckpt:"
            records = gics.scan(prefix=prefix)

            for record in records:
                key = record.get("key", "")
                if key.endswith(f":{checkpoint_id}"):
                    fields = record.get("fields") or {}

                    # Check if expired
                    expires_at = fields.get("expires_at", 0)
                    if time.time() > expires_at:
                        logger.warning("Checkpoint %s expired", checkpoint_id)
                        return None

                    logger.debug("Checkpoint retrieved: %s", checkpoint_id)
                    return fields

            logger.warning("Checkpoint not found: %s", checkpoint_id)
            return None

        except Exception as exc:
            logger.error("Failed to retrieve checkpoint %s: %s", checkpoint_id, exc, exc_info=True)
            return None

    @classmethod
    def list_resumable(
        cls,
        operation: Optional[str] = None,
        operation_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Lista checkpoints resumables.

        Args:
            operation: Filter by operation type (optional)
            operation_id: Filter by operation ID (optional)
            limit: Maximum checkpoints to return

        Returns:
            List of checkpoint metadata dicts (most recent first)
        """
        try:
            gics = cls._get_gics()

            # Build prefix for filtering
            if operation and operation_id:
                prefix = f"ckpt:{operation}:{operation_id}:"
            elif operation:
                prefix = f"ckpt:{operation}:"
            else:
                prefix = "ckpt:"

            records = gics.scan(prefix=prefix)

            # Filter and sort
            checkpoints = []
            current_time = time.time()

            for record in records:
                fields = record.get("fields") or {}

                # Filter expired
                expires_at = fields.get("expires_at", 0)
                if current_time > expires_at:
                    continue

                # Filter non-resumable
                if not fields.get("resumable", False):
                    continue

                checkpoints.append({
                    "checkpoint_id": fields.get("checkpoint_id"),
                    "operation": fields.get("operation"),
                    "operation_id": fields.get("operation_id"),
                    "timestamp": fields.get("timestamp"),
                    "expires_at": fields.get("expires_at"),
                    "metadata": fields.get("metadata", {}),
                })

            # Sort by timestamp (most recent first)
            checkpoints.sort(key=lambda x: x["timestamp"], reverse=True)

            # Limit results
            return checkpoints[:limit]

        except Exception as exc:
            logger.error("Failed to list resumable checkpoints: %s", exc, exc_info=True)
            return []

    @classmethod
    def delete_checkpoint(cls, checkpoint_id: str) -> bool:
        """
        Elimina checkpoint de GICS.

        Args:
            checkpoint_id: Checkpoint identifier

        Returns:
            True if deleted successfully
        """
        try:
            gics = cls._get_gics()

            # Find checkpoint key
            prefix = "ckpt:"
            records = gics.scan(prefix=prefix)

            for record in records:
                key = record.get("key", "")
                if key.endswith(f":{checkpoint_id}"):
                    gics.delete(key)
                    logger.info("Checkpoint deleted: %s", checkpoint_id)
                    return True

            logger.warning("Checkpoint not found for deletion: %s", checkpoint_id)
            return False

        except Exception as exc:
            logger.error("Failed to delete checkpoint %s: %s", checkpoint_id, exc, exc_info=True)
            return False

    @classmethod
    def cleanup_expired(cls) -> int:
        """
        Limpia checkpoints expirados de GICS.

        Returns:
            Number of checkpoints cleaned up
        """
        try:
            gics = cls._get_gics()
            prefix = "ckpt:"
            records = gics.scan(prefix=prefix)

            current_time = time.time()
            cleaned = 0

            for record in records:
                fields = record.get("fields") or {}
                expires_at = fields.get("expires_at", 0)

                if current_time > expires_at:
                    key = record.get("key")
                    if key:
                        gics.delete(key)
                        cleaned += 1

            if cleaned > 0:
                logger.info("Cleaned up %d expired checkpoints", cleaned)

            return cleaned

        except Exception as exc:
            logger.error("Failed to cleanup expired checkpoints: %s", exc, exc_info=True)
            return 0

    @classmethod
    def mark_non_resumable(cls, checkpoint_id: str) -> bool:
        """
        Marca checkpoint como no resumable (completado o abandonado).

        Args:
            checkpoint_id: Checkpoint identifier

        Returns:
            True if updated successfully
        """
        try:
            gics = cls._get_gics()

            # Find and update checkpoint
            prefix = "ckpt:"
            records = gics.scan(prefix=prefix)

            for record in records:
                key = record.get("key", "")
                if key.endswith(f":{checkpoint_id}"):
                    fields = record.get("fields") or {}
                    fields["resumable"] = False
                    gics.put(key, fields)
                    logger.debug("Checkpoint marked non-resumable: %s", checkpoint_id)
                    return True

            return False

        except Exception as exc:
            logger.error(
                "Failed to mark checkpoint non-resumable %s: %s",
                checkpoint_id, exc, exc_info=True
            )
            return False

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """
        Obtiene estadísticas de checkpoints.

        Returns:
            {
                "total_checkpoints": int,
                "resumable_checkpoints": int,
                "expired_checkpoints": int,
                "by_operation": dict,
            }
        """
        try:
            gics = cls._get_gics()
            prefix = "ckpt:"
            records = gics.scan(prefix=prefix)

            current_time = time.time()
            total = len(records)
            resumable = 0
            expired = 0
            by_operation = {}

            for record in records:
                fields = record.get("fields") or {}
                expires_at = fields.get("expires_at", 0)
                is_resumable = fields.get("resumable", False)
                operation = fields.get("operation", "unknown")

                if current_time > expires_at:
                    expired += 1
                elif is_resumable:
                    resumable += 1

                by_operation[operation] = by_operation.get(operation, 0) + 1

            return {
                "total_checkpoints": total,
                "resumable_checkpoints": resumable,
                "expired_checkpoints": expired,
                "by_operation": by_operation,
            }

        except Exception as exc:
            logger.error("Failed to get checkpoint stats: %s", exc, exc_info=True)
            return {
                "total_checkpoints": 0,
                "resumable_checkpoints": 0,
                "expired_checkpoints": 0,
                "by_operation": {},
            }
