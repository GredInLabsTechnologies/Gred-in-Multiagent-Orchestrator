"""Utility task queue — assigns, tracks, and expires lightweight tasks for mesh devices."""

from __future__ import annotations

import json
import logging
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock

from ...config import OPS_DATA_DIR
from ...models.mesh import (
    DeviceMode,
    MeshDeviceInfo,
    MeshTask,
    OperationalState,
    TaskResult,
    TaskStatus,
    UtilityTaskType,
    TASK_TYPE_REQUIREMENTS,
)
from .registry import MeshRegistry

logger = logging.getLogger("orchestrator.mesh.task_queue")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskQueue:
    """File-backed task queue for utility-mode mesh devices.

    Storage: .orch_data/ops/mesh/tasks/<task_id>.json
    Same atomic-write pattern as MeshRegistry.
    """

    TASKS_DIR = Path(OPS_DATA_DIR) / "mesh" / "tasks"
    LOCK_FILE = Path(OPS_DATA_DIR) / "mesh" / ".tasks.lock"

    def __init__(self, registry: MeshRegistry) -> None:
        self._registry = registry
        self.TASKS_DIR.mkdir(parents=True, exist_ok=True)

    def _lock(self) -> FileLock:
        return FileLock(str(self.LOCK_FILE), timeout=5)

    def _task_path(self, task_id: str) -> Path:
        return self.TASKS_DIR / f"{task_id}.json"

    # ── CRUD ─────────────────────────────────────────────────

    def _load_task(self, task_id: str) -> Optional[MeshTask]:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return MeshTask(**data)
        except Exception as e:
            logger.error("Failed to load task %s: %s", task_id, e)
            return None

    def _save_task(self, task: MeshTask) -> None:
        path = self._task_path(task.task_id)
        data = task.model_dump(mode="json")
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self.TASKS_DIR), suffix=".tmp"
        )
        try:
            import os
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            Path(tmp_path).replace(path)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def create_task(
        self,
        task_type: UtilityTaskType,
        payload: Dict[str, Any],
        timeout_seconds: int = 60,
        min_ram_mb: int = 0,
        min_api_level: int = 0,
        requires_arch: str = "",
        workspace_id: str = "default",
    ) -> MeshTask:
        task_id = f"t-{uuid.uuid4().hex[:12]}"

        # Apply default requirements if not overridden
        defaults = TASK_TYPE_REQUIREMENTS.get(task_type.value, {})
        if min_ram_mb == 0:
            min_ram_mb = defaults.get("min_ram_mb", 0)

        task = MeshTask(
            task_id=task_id,
            task_type=task_type,
            workspace_id=workspace_id,  # INV-T2: task belongs to 1 workspace
            payload=payload,
            timeout_seconds=timeout_seconds,
            min_ram_mb=min_ram_mb,
            min_api_level=min_api_level,
            requires_arch=requires_arch,
        )
        with self._lock():
            self._save_task(task)
        logger.info("Created task %s type=%s", task_id, task_type.value)
        return task

    def get_task(self, task_id: str) -> Optional[MeshTask]:
        return self._load_task(task_id)

    def list_tasks(self, status: Optional[TaskStatus] = None) -> List[MeshTask]:
        tasks = []
        for path in self.TASKS_DIR.glob("t-*.json"):
            task = self._load_task(path.stem)
            if task and (status is None or task.status == status):
                tasks.append(task)
        tasks.sort(key=lambda t: t.created_at)
        return tasks

    def delete_task(self, task_id: str) -> bool:
        path = self._task_path(task_id)
        if path.exists():
            path.unlink()
            return True
        return False

    # ── Assignment ───────────────────────────────────────────

    def can_device_handle(self, device: MeshDeviceInfo, task: MeshTask) -> bool:
        """Capability gate — reject if hardware insufficient or device unhealthy."""
        cap = device.capabilities

        # RAM check
        if cap and task.min_ram_mb > 0 and cap.ram_total_mb < task.min_ram_mb:
            return False

        # API level check
        if cap and task.min_api_level > 0 and cap.api_level < task.min_api_level:
            return False

        # Arch check
        if task.requires_arch and cap and cap.arch != task.requires_arch:
            return False

        # Thermal throttle — only ping allowed
        if device.thermal_throttled and task.task_type != UtilityTaskType.ping:
            return False

        # Battery too low (not charging)
        if device.battery_percent >= 0 and device.battery_percent < 20 and not device.battery_charging:
            return False

        # RAM usage too high
        if device.ram_percent > 85:
            return False

        # CPU saturated
        if device.cpu_percent > 90:
            return False

        return True

    def assign_task(self, task_id: str, device_id: str) -> Optional[MeshTask]:
        with self._lock():
            task = self._load_task(task_id)
            if not task or task.status != TaskStatus.pending:
                return None
            task.assigned_device_id = device_id
            task.status = TaskStatus.assigned
            task.assigned_at = _utcnow()
            self._save_task(task)
        logger.info("Assigned task %s to device %s", task_id, device_id)
        return task

    def get_assigned_for_device(self, device_id: str, workspace_id: str = "") -> List[MeshTask]:
        """INV-W1: only return tasks for the device's active workspace."""
        device = self._registry.get_device(device_id) if not workspace_id else None
        ws_id = workspace_id or (device.active_workspace_id if device else "default")
        tasks = []
        for path in self.TASKS_DIR.glob("t-*.json"):
            task = self._load_task(path.stem)
            if (
                task
                and task.assigned_device_id == device_id
                and task.workspace_id == ws_id
                and task.status in (TaskStatus.assigned, TaskStatus.running)
            ):
                tasks.append(task)
        tasks.sort(key=lambda t: t.created_at)
        return tasks

    # ── Completion ───────────────────────────────────────────

    def complete_task(self, result: TaskResult) -> Optional[MeshTask]:
        with self._lock():
            task = self._load_task(result.task_id)
            if not task:
                return None
            if result.status == "completed":
                task.status = TaskStatus.completed
                task.result = result.result
            else:
                task.status = TaskStatus.failed
                task.error = result.error
            task.completed_at = _utcnow()
            self._save_task(task)
        logger.info(
            "Task %s %s by device %s in %dms",
            result.task_id, result.status, result.device_id, result.duration_ms,
        )
        return task

    # ── Expiration ───────────────────────────────────────────

    def expire_stale(self) -> List[str]:
        """Move assigned tasks past their timeout to timed_out."""
        expired = []
        now = _utcnow()
        with self._lock():
            for path in self.TASKS_DIR.glob("t-*.json"):
                task = self._load_task(path.stem)
                if not task or task.status != TaskStatus.assigned:
                    continue
                if task.assigned_at:
                    elapsed = (now - task.assigned_at).total_seconds()
                    if elapsed > task.timeout_seconds:
                        task.status = TaskStatus.timed_out
                        task.completed_at = now
                        task.error = f"timed out after {int(elapsed)}s"
                        self._save_task(task)
                        expired.append(task.task_id)
                        # Clear device's active_task_id so it's not stuck
                        if task.assigned_device_id:
                            device = self._registry.get_device(task.assigned_device_id)
                            if device and device.active_task_id == task.task_id:
                                device.active_task_id = ""
                                self._registry.save_device(device)
                        logger.warning("Task %s timed out", task.task_id)
        return expired

    # ── Auto-assign ──────────────────────────────────────────

    def auto_assign_pending(self, mesh_enabled: bool) -> int:
        """Assign pending tasks to idle utility/hybrid devices with capacity.
        INV-W1: tasks only assigned to devices in the same workspace.
        INV-W6: skip workspaces without an active Core device."""
        if not mesh_enabled:
            return 0

        pending = self.list_tasks(status=TaskStatus.pending)
        if not pending:
            return 0

        # Get idle utility/hybrid devices
        eligible = [
            d for d in self._registry.get_eligible_devices(mesh_enabled)
            if d.device_mode in (DeviceMode.utility, DeviceMode.hybrid)
            and d.operational_state == OperationalState.idle
            and d.active_task_id == ""
        ]
        if not eligible:
            return 0

        # INV-W6: cache which workspaces have an active Core
        from tools.gimo_server.services.mesh.workspace_service import WorkspaceService
        ws_svc = getattr(self._registry, "_ws_svc_cache", None) or WorkspaceService()
        self._registry._ws_svc_cache = ws_svc
        _core_cache: dict[str, bool] = {}

        assigned_count = 0
        device_idx = 0

        for task in pending:
            if device_idx >= len(eligible):
                break

            # INV-W6: skip tasks in workspaces without active Core
            ws_id = task.workspace_id
            if ws_id not in _core_cache:
                _core_cache[ws_id] = ws_svc.has_active_core(ws_id, self._registry)
            if not _core_cache[ws_id]:
                continue

            # Find a device that can handle this task (INV-W1: workspace match)
            for i in range(device_idx, len(eligible)):
                device = eligible[i]
                if device.active_workspace_id != task.workspace_id:
                    continue  # Wrong workspace
                if self.can_device_handle(device, task):
                    self.assign_task(task.task_id, device.device_id)
                    assigned_count += 1
                    device_idx = i + 1  # Move to next device
                    break

        return assigned_count
