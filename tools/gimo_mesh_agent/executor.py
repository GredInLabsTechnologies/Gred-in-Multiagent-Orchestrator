"""Task execution wrapper for mesh devices.

Handles inference and utility mode execution with receipts.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

from .config import AgentConfig
from .thermal import ThermalGuard

logger = logging.getLogger("gimo_mesh_agent.executor")


@dataclass
class TaskReceipt:
    """Immutable record of a task execution."""
    receipt_id: str = ""
    task_id: str = ""
    device_id: str = ""
    action_class: str = ""
    model_used: str = ""
    started_at: str = ""
    finished_at: str = ""
    success: bool = False
    error: str = ""
    latency_ms: float = 0.0
    thermal_phase_at_start: str = "normal"
    thermal_phase_at_end: str = "normal"
    aborted_by_lockout: bool = False
    result_payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "task_id": self.task_id,
            "device_id": self.device_id,
            "action_class": self.action_class,
            "model_used": self.model_used,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "success": self.success,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "thermal_phase_at_start": self.thermal_phase_at_start,
            "thermal_phase_at_end": self.thermal_phase_at_end,
            "aborted_by_lockout": self.aborted_by_lockout,
            "result_payload": self.result_payload,
        }


class TaskExecutor:
    """Executes tasks on the mesh device with thermal protection and receipts."""

    def __init__(
        self,
        config: AgentConfig,
        thermal_guard: ThermalGuard,
    ) -> None:
        self._config = config
        self._thermal = thermal_guard
        self._receipts_dir = config.resolved_data_dir / "receipts"
        self._receipts_dir.mkdir(parents=True, exist_ok=True)
        self._current_task_id: str = ""

    @property
    def current_task_id(self) -> str:
        return self._current_task_id

    async def execute(
        self,
        task_id: str,
        action_class: str,
        payload: Dict[str, Any],
        model: str = "",
    ) -> TaskReceipt:
        """Execute a task with thermal monitoring and receipt generation.

        If thermal lockout occurs during execution, the task is aborted.
        """
        receipt = TaskReceipt(
            receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            device_id=self._config.device_id,
            action_class=action_class,
            model_used=model,
            started_at=datetime.now(timezone.utc).isoformat(),
            thermal_phase_at_start=self._thermal.phase.value,
        )

        # Block execution if already locked out
        if self._thermal.is_locked_out:
            receipt.error = "Device in thermal lockout"
            receipt.aborted_by_lockout = True
            receipt.finished_at = datetime.now(timezone.utc).isoformat()
            self._save_receipt(receipt)
            return receipt

        # Block if local control disallows
        if not self._config.allow_task_execution:
            receipt.error = "Task execution disabled by local control"
            receipt.finished_at = datetime.now(timezone.utc).isoformat()
            self._save_receipt(receipt)
            return receipt

        self._current_task_id = task_id
        start_time = time.monotonic()

        try:
            if action_class == "inference" and model:
                result = await self._run_inference(model, payload)
            else:
                result = await self._run_utility(action_class, payload)

            receipt.result_payload = result or {}
            receipt.success = True
            receipt.latency_ms = (time.monotonic() - start_time) * 1000

        except _ThermalAbort:
            receipt.error = "Aborted by thermal lockout during execution"
            receipt.aborted_by_lockout = True
            receipt.latency_ms = (time.monotonic() - start_time) * 1000

        except Exception as exc:
            receipt.error = str(exc)[:500]
            receipt.latency_ms = (time.monotonic() - start_time) * 1000

        finally:
            self._current_task_id = ""
            receipt.finished_at = datetime.now(timezone.utc).isoformat()
            receipt.thermal_phase_at_end = self._thermal.phase.value
            self._save_receipt(receipt)

        return receipt

    async def _run_inference(self, model: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run inference task. Placeholder for actual Ollama/model integration."""
        logger.info("Executing inference task with model=%s", model)
        # Check thermal state before inference
        if self._thermal.is_locked_out:
            raise _ThermalAbort()
        # Placeholder — actual implementation will call Ollama or local model
        return {"status": "completed", "model": model}

    async def _run_utility(self, action_class: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run utility task (no model needed). Placeholder."""
        logger.info("Executing utility task: %s", action_class)
        if self._thermal.is_locked_out:
            raise _ThermalAbort()
        return {"status": "completed", "action": action_class}

    def _save_receipt(self, receipt: TaskReceipt) -> None:
        path = self._receipts_dir / f"{receipt.receipt_id}.json"
        try:
            path.write_text(
                json.dumps(receipt.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to save receipt %s", receipt.receipt_id)

    def list_receipts(self, limit: int = 50) -> list[Dict[str, Any]]:
        receipts = []
        for p in sorted(self._receipts_dir.glob("rcpt_*.json"), reverse=True)[:limit]:
            try:
                receipts.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return receipts


class _ThermalAbort(Exception):
    """Internal: raised when thermal lockout occurs during execution."""
