"""Unified Execution Authority — single source of truth for all runtime services.

Every component that needs access to RunWorker, HardwareMonitor, or ResourceGovernor
must go through ExecutionAuthority.get() instead of creating its own instances.
"""

from __future__ import annotations

import logging
from typing import ClassVar, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .execution.run_worker import RunWorker
    from .hardware_monitor_service import HardwareMonitorService
    from .resource_governor import ResourceGovernor

logger = logging.getLogger("orchestrator.authority")


class ExecutionAuthority:
    """Singleton that owns all runtime-critical service instances."""

    _instance: ClassVar[Optional["ExecutionAuthority"]] = None

    def __init__(
        self,
        run_worker: "RunWorker",
        hardware_monitor: "HardwareMonitorService",
        resource_governor: "ResourceGovernor",
    ) -> None:
        self.run_worker = run_worker
        self.hardware_monitor = hardware_monitor
        self.resource_governor = resource_governor

    @classmethod
    def initialize(
        cls,
        run_worker: "RunWorker",
        hardware_monitor: "HardwareMonitorService",
        resource_governor: "ResourceGovernor",
    ) -> "ExecutionAuthority":
        """Create the singleton. Must be called exactly once during lifespan startup."""
        if cls._instance is not None:
            raise RuntimeError("ExecutionAuthority already initialized")
        cls._instance = cls(run_worker, hardware_monitor, resource_governor)
        logger.info("ExecutionAuthority initialized")
        return cls._instance

    @classmethod
    def get(cls) -> "ExecutionAuthority":
        """Return the singleton. Raises if not yet initialized."""
        if cls._instance is None:
            raise RuntimeError("ExecutionAuthority not initialized — call initialize() first")
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Testing helper."""
        cls._instance = None
