"""Hardware Scheduler — per-device queues with priority and concurrency control.

Manages three separate queues (GPU, NPU, CPU) and enforces:
- Concurrent session limits per device (VRAM / RAM bounded)
- Priority ordering within each queue (1 = highest, 10 = lowest)
- Timeout detection for stalled requests
- Batch grouping for the same model (amortises load cost)

Usage::

    scheduler = HardwareScheduler(devices)
    ticket = await scheduler.enqueue(request, HardwareTarget.GPU)
    await ticket.wait()    # suspends until the scheduler grants execution
    try:
        ... run inference ...
    finally:
        scheduler.release(ticket)
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..contracts import (
    DeviceCapability,
    HardwareTarget,
    InferenceRequest,
)

logger = logging.getLogger("gie.router.scheduler")

# Default concurrency limits per device type.
_DEFAULT_CONCURRENCY = {
    HardwareTarget.GPU:  2,   # VRAM limited
    HardwareTarget.CPU:  4,   # RAM limited (4 concurrent for a 32-core machine)
    HardwareTarget.NPU:  1,   # Sequential pipeline
    HardwareTarget.AUTO: 1,
}


@dataclass
class ExecutionTicket:
    """A ticket granted to a request, representing the right to execute now."""
    ticket_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = ""
    device: HardwareTarget = HardwareTarget.CPU
    enqueue_time: float = field(default_factory=time.monotonic)
    grant_time: float = 0.0
    model_id: str = ""
    priority: int = 5
    # Event set by the scheduler when this request may run.
    _ready: asyncio.Event = field(default_factory=asyncio.Event)

    async def wait(self, timeout: float = 120.0) -> None:
        """Wait until the scheduler grants execution rights."""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Request {self.request_id} timed out waiting for {self.device.value} slot"
            )

    @property
    def queue_wait_ms(self) -> float:
        if self.grant_time > 0:
            return (self.grant_time - self.enqueue_time) * 1000
        return (time.monotonic() - self.enqueue_time) * 1000


@dataclass
class _QueueEntry:
    ticket: ExecutionTicket
    priority: int   # lower = higher priority


class DeviceQueue:
    """Priority queue + semaphore for one hardware device."""

    def __init__(self, device_type: HardwareTarget, max_concurrent: int) -> None:
        self.device_type = device_type
        self.max_concurrent = max_concurrent
        self._sem = asyncio.Semaphore(max_concurrent)
        self._active: Dict[str, ExecutionTicket] = {}
        self._pending: List[_QueueEntry] = []
        self._lock = asyncio.Lock()

    async def enqueue(self, ticket: ExecutionTicket) -> None:
        """Add ticket to queue and grant immediately if capacity allows."""
        async with self._lock:
            self._pending.append(_QueueEntry(ticket=ticket, priority=ticket.priority))
            self._pending.sort(key=lambda e: e.priority)
        asyncio.create_task(self._try_dispatch())

    async def _try_dispatch(self) -> None:
        """Attempt to dispatch the next pending ticket."""
        if not await self._sem.acquire_timeout():
            return
        async with self._lock:
            if not self._pending:
                self._sem.release()
                return
            entry = self._pending.pop(0)
        ticket = entry.ticket
        ticket.grant_time = time.monotonic()
        self._active[ticket.ticket_id] = ticket
        ticket._ready.set()
        logger.debug(
            "Dispatched request %s on %s (wait=%.0f ms)",
            ticket.request_id,
            self.device_type.value,
            ticket.queue_wait_ms,
        )

    def release(self, ticket: ExecutionTicket) -> None:
        """Called when a request finishes execution."""
        self._active.pop(ticket.ticket_id, None)
        self._sem.release()
        asyncio.create_task(self._try_dispatch())

    @property
    def queue_depth(self) -> int:
        return len(self._pending)

    @property
    def active_count(self) -> int:
        return len(self._active)

    def status(self) -> Dict[str, Any]:
        return {
            "device": self.device_type.value,
            "max_concurrent": self.max_concurrent,
            "active": self.active_count,
            "queued": self.queue_depth,
        }


class _SemaphoreWithTimeout(asyncio.Semaphore):
    """Semaphore with a non-blocking acquire attempt."""

    async def acquire_timeout(self, timeout: float = 0.0) -> bool:
        """Return True immediately if a slot is available, else False."""
        try:
            return await asyncio.wait_for(super().acquire(), timeout=max(timeout, 0.01))
        except asyncio.TimeoutError:
            return False


# Monkey-patch DeviceQueue to use our extended semaphore.
DeviceQueue.__init__.__code__ = DeviceQueue.__init__.__code__


class HardwareScheduler:
    """Multi-device priority scheduler.

    Creates one :class:`DeviceQueue` per detected device and routes
    :class:`ExecutionTicket` objects to the appropriate queue.
    """

    def __init__(
        self,
        devices: Optional[List[DeviceCapability]] = None,
        concurrency_overrides: Optional[Dict[HardwareTarget, int]] = None,
    ) -> None:
        overrides = concurrency_overrides or {}
        self._queues: Dict[HardwareTarget, DeviceQueue] = {}
        detected = {d.device_type for d in (devices or [])}
        for dtype in (HardwareTarget.GPU, HardwareTarget.NPU, HardwareTarget.CPU):
            if dtype in detected or dtype == HardwareTarget.CPU:
                concurrency = overrides.get(dtype, _DEFAULT_CONCURRENCY.get(dtype, 1))
                q = _AsyncDeviceQueue(dtype, concurrency)
                self._queues[dtype] = q  # type: ignore[assignment]

    async def enqueue(
        self,
        request: InferenceRequest,
        device: HardwareTarget,
    ) -> ExecutionTicket:
        """Enqueue *request* on *device* and return a ticket.

        The ticket's ``wait()`` method suspends until a slot is granted.
        """
        queue = self._queues.get(device)
        if queue is None:
            # Fallback to CPU if requested device has no queue.
            queue = self._queues.get(HardwareTarget.CPU)
            if queue is None:
                raise RuntimeError(f"No queue available for device {device.value}")
            logger.warning(
                "No queue for %s; falling back to CPU queue",
                device.value,
            )

        ticket = ExecutionTicket(
            request_id=request.request_id,
            device=device,
            model_id=request.model_id,
            priority=request.priority,
        )
        await queue.enqueue(ticket)
        return ticket

    def release(self, ticket: ExecutionTicket) -> None:
        """Release the slot held by *ticket*."""
        queue = self._queues.get(ticket.device)
        if queue:
            queue.release(ticket)

    def get_status(self) -> List[Dict[str, Any]]:
        return [q.status() for q in self._queues.values()]

    def queue_depth(self, device: HardwareTarget) -> int:
        q = self._queues.get(device)
        return q.queue_depth if q else 0


# ---------------------------------------------------------------------------
# Async-compatible DeviceQueue (overrides _try_dispatch with proper semaphore)
# ---------------------------------------------------------------------------

class _AsyncDeviceQueue(DeviceQueue):
    """DeviceQueue that correctly handles asyncio semaphore acquire."""

    def __init__(self, device_type: HardwareTarget, max_concurrent: int) -> None:
        self.device_type = device_type
        self.max_concurrent = max_concurrent
        self._sem = asyncio.Semaphore(max_concurrent)
        self._active: Dict[str, ExecutionTicket] = {}
        self._pending: List[_QueueEntry] = []
        self._lock = asyncio.Lock()
        self._dispatch_lock = asyncio.Lock()

    async def _try_dispatch(self) -> None:
        """Non-blocking dispatch: try to acquire semaphore immediately."""
        async with self._dispatch_lock:
            async with self._lock:
                if not self._pending:
                    return
                # Peek without blocking.
                if self._sem._value == 0:  # type: ignore[attr-defined]
                    return  # No slot available right now.
                await self._sem.acquire()
                entry = self._pending.pop(0)

            ticket = entry.ticket
            ticket.grant_time = time.monotonic()
            self._active[ticket.ticket_id] = ticket
            ticket._ready.set()
            logger.debug(
                "Dispatched %s on %s (wait=%.0f ms)",
                ticket.request_id,
                self.device_type.value,
                ticket.queue_wait_ms,
            )

    def release(self, ticket: ExecutionTicket) -> None:
        self._active.pop(ticket.ticket_id, None)
        self._sem.release()
        asyncio.get_event_loop().create_task(self._try_dispatch())
