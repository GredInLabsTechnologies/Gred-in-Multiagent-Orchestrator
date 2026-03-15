"""Load balancer — distribute requests across devices of the same type.

Implements weighted round-robin by free memory, with a fallback chain:
    GPU → NPU → CPU → (future: cloud)

For multi-GPU setups, distributes requests across all GPUs proportionally
to their free VRAM.

Also handles thermal throttling: if a GPU exceeds the warn temperature,
it gets a reduced weight; if it exceeds critical, it is removed from rotation.
"""
from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional

from ..contracts import DeviceCapability, HardwareTarget

logger = logging.getLogger("gie.router.load_balancer")

_TEMP_WARN     = 80.0
_TEMP_CRITICAL = 90.0
_MIN_FREE_GB   = 0.5   # skip devices with less than this free memory


class LoadBalancer:
    """Weighted random selection across same-type devices.

    Args:
        devices: All detected devices.
    """

    def __init__(self, devices: Optional[List[DeviceCapability]] = None) -> None:
        self._devices: List[DeviceCapability] = devices or []

    def update_devices(self, devices: List[DeviceCapability]) -> None:
        self._devices = devices

    def select(
        self,
        preferred_type: HardwareTarget,
    ) -> Optional[DeviceCapability]:
        """Return the best device of *preferred_type*, or fall back.

        Fallback chain: GPU → NPU → CPU.
        """
        chain = _fallback_chain(preferred_type)
        for dtype in chain:
            candidate = self._best_of_type(dtype)
            if candidate is not None:
                return candidate
        return None

    def fallback(self, failed_type: HardwareTarget) -> Optional[DeviceCapability]:
        """Return the next viable device after *failed_type* fails."""
        chain = _fallback_chain(failed_type)
        # Skip the failed type itself.
        for dtype in chain:
            if dtype == failed_type:
                continue
            candidate = self._best_of_type(dtype)
            if candidate is not None:
                logger.info(
                    "Load balancer fallback: %s → %s",
                    failed_type.value,
                    dtype.value,
                )
                return candidate
        return None

    def _best_of_type(self, dtype: HardwareTarget) -> Optional[DeviceCapability]:
        """Weighted random selection among healthy devices of *dtype*."""
        pool = [
            d for d in self._devices
            if d.device_type == dtype
            and d.free_memory_gb >= _MIN_FREE_GB
            and d.temperature_celsius < _TEMP_CRITICAL
        ]
        if not pool:
            return None
        if len(pool) == 1:
            return pool[0]

        # Compute weights: prefer more free memory; penalise high temperature.
        weights = []
        for dev in pool:
            w = dev.free_memory_gb
            if dev.temperature_celsius >= _TEMP_WARN:
                w *= 0.5    # deprioritise hot devices
            weights.append(max(w, 0.01))

        return random.choices(pool, weights=weights, k=1)[0]  # noqa: S311

    def get_device_weights(self, dtype: HardwareTarget) -> Dict[str, float]:
        """For debugging: return weight map {device_name: weight}."""
        pool = [d for d in self._devices if d.device_type == dtype]
        result: Dict[str, float] = {}
        for dev in pool:
            w = dev.free_memory_gb
            if dev.temperature_celsius >= _TEMP_WARN:
                w *= 0.5
            result[dev.device_name] = round(w, 2)
        return result


def _fallback_chain(preferred: HardwareTarget) -> List[HardwareTarget]:
    """Return the device type fallback chain starting from *preferred*."""
    chain = [HardwareTarget.GPU, HardwareTarget.NPU, HardwareTarget.CPU]
    if preferred in chain:
        idx = chain.index(preferred)
        return chain[idx:] + chain[:idx]
    return chain
