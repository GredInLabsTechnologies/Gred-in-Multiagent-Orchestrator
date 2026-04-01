"""
Progress Emitter — Phase 3 of SEA (Sistema de Ejecución Adaptativa).

Emits SSE progress events during long-running operations.
"""

import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("orchestrator.services.timeout.progress_emitter")


class ProgressEmitter:
    """Emite eventos de progreso vía callback para SSE streaming."""

    def __init__(self, emit_fn: Callable[[str, Dict[str, Any]], None]):
        """
        Initialize progress emitter.

        Args:
            emit_fn: Callback function to emit events
                     Signature: (event_type: str, data: dict) -> None
        """
        self.emit_fn = emit_fn
        self.start_time = time.time()
        self.estimated_duration: Optional[float] = None
        self.last_progress: float = 0.0

    async def emit_started(
        self,
        operation: str,
        estimated_duration: float,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Emite evento de inicio con duración estimada.

        Args:
            operation: Operation type (e.g., "plan", "run")
            estimated_duration: Estimated duration in seconds
            metadata: Optional additional metadata
        """
        self.estimated_duration = estimated_duration

        data = {
            "operation": operation,
            "estimated_duration": round(estimated_duration, 1),
            "timestamp": time.time(),
        }

        if metadata:
            data["metadata"] = metadata

        await self.emit_fn("started", data)

        logger.debug(
            "Progress started: %s (estimated %.1fs)",
            operation, estimated_duration
        )

    async def emit_progress(
        self,
        stage: str,
        progress: float,
        message: Optional[str] = None
    ) -> None:
        """
        Emite evento de progreso.

        Args:
            stage: Current stage name (e.g., "analyzing_prompt", "generating_tasks")
            progress: Progress value (0.0 to 1.0)
            message: Optional progress message
        """
        # Clamp progress to [0.0, 1.0]
        progress = max(0.0, min(1.0, progress))

        elapsed = time.time() - self.start_time
        remaining: Optional[float] = None

        if self.estimated_duration:
            remaining = max(0.0, self.estimated_duration - elapsed)

        data = {
            "stage": stage,
            "progress": round(progress, 3),
            "elapsed": round(elapsed, 1),
        }

        if remaining is not None:
            data["remaining"] = round(remaining, 1)

        if message:
            data["message"] = message

        await self.emit_fn("progress", data)

        # Log only on significant progress changes (>5%)
        if progress - self.last_progress >= 0.05:
            logger.debug(
                "Progress: %s — %.0f%% (%.1fs elapsed, ~%.1fs remaining)",
                stage, progress * 100, elapsed, remaining or 0
            )
            self.last_progress = progress

    async def emit_checkpoint(
        self,
        checkpoint_id: str,
        resumable: bool = True
    ) -> None:
        """
        Emite evento de checkpoint guardado.

        Args:
            checkpoint_id: Checkpoint identifier
            resumable: Whether operation can be resumed from this checkpoint
        """
        data = {
            "checkpoint_id": checkpoint_id,
            "resumable": resumable,
            "timestamp": time.time(),
        }

        await self.emit_fn("checkpoint", data)

        logger.info("Checkpoint saved: %s (resumable=%s)", checkpoint_id, resumable)

    async def emit_completed(
        self,
        result: Dict[str, Any],
        status: str = "success"
    ) -> None:
        """
        Emite evento de operación completada.

        Args:
            result: Operation result data
            status: Completion status ("success", "partial_success", "error")
        """
        duration = time.time() - self.start_time

        data = {
            "result": result,
            "duration": round(duration, 1),
            "status": status,
            "timestamp": time.time(),
        }

        await self.emit_fn("completed", data)

        logger.info(
            "Operation completed: status=%s, duration=%.1fs",
            status, duration
        )

    async def emit_error(
        self,
        error: str,
        error_code: Optional[str] = None
    ) -> None:
        """
        Emite evento de error.

        Args:
            error: Error message
            error_code: Optional error code
        """
        elapsed = time.time() - self.start_time

        data = {
            "error": error,
            "elapsed": round(elapsed, 1),
            "timestamp": time.time(),
        }

        if error_code:
            data["error_code"] = error_code

        await self.emit_fn("error", data)

        logger.error("Operation error after %.1fs: %s", elapsed, error)

    async def emit_custom(
        self,
        event_type: str,
        data: Dict[str, Any]
    ) -> None:
        """
        Emite evento personalizado.

        Args:
            event_type: Custom event type
            data: Event data
        """
        await self.emit_fn(event_type, data)

        logger.debug("Custom event: %s — %s", event_type, data)

    def get_elapsed_time(self) -> float:
        """Retorna tiempo transcurrido en segundos."""
        return time.time() - self.start_time

    def get_remaining_time(self) -> Optional[float]:
        """Retorna tiempo restante estimado en segundos (None si no estimado)."""
        if not self.estimated_duration:
            return None

        elapsed = self.get_elapsed_time()
        remaining = self.estimated_duration - elapsed
        return max(0.0, remaining)

    def should_emit_checkpoint(self, checkpoint_interval: float = 15.0) -> bool:
        """
        Determina si es momento de emitir checkpoint.

        Args:
            checkpoint_interval: Seconds between checkpoints (default 15s)

        Returns:
            True if checkpoint should be emitted
        """
        # Simple heuristic: emit checkpoint every N seconds
        elapsed = self.get_elapsed_time()
        return elapsed > 0 and (elapsed % checkpoint_interval) < 1.0
