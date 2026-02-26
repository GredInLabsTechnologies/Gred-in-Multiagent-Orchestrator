from __future__ import annotations

import os
import platform
import sys
import time
from dataclasses import dataclass, field


VM_KEYWORDS = (
    "virtual",
    "vmware",
    "virtualbox",
    "qemu",
    "kvm",
    "xen",
    "hyper-v",
)


@dataclass
class RuntimeGuardReport:
    debugger_detected: bool = False
    timing_anomaly: bool = False
    vm_detected: bool = False
    vm_indicators: list[str] = field(default_factory=list)
    blocked: bool = False
    reasons: list[str] = field(default_factory=list)


class RuntimeGuard:
    """Runtime anti-tamper checks used at startup.

    Current checks are intentionally conservative to avoid false positives.
    """

    def __init__(self, settings):
        self._enabled = bool(getattr(settings, "runtime_guard_enabled", True))
        self._block_debugger = bool(getattr(settings, "runtime_guard_block_debugger", False))
        self._timing_threshold_ms = int(getattr(settings, "runtime_guard_timing_threshold_ms", 500))

    @staticmethod
    def _is_debugger_attached() -> bool:
        if sys.gettrace() is not None:
            return True
        if hasattr(sys, "getprofile") and sys.getprofile() is not None:
            return True

        # Windows native check (best effort)
        if sys.platform == "win32":
            try:
                import ctypes

                return bool(ctypes.windll.kernel32.IsDebuggerPresent())
            except Exception:
                return False
        return False

    @staticmethod
    def _timing_anomaly(threshold_ms: int = 500) -> bool:
        start = time.perf_counter_ns()
        _ = sum(range(1000))
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return elapsed_ms > threshold_ms

    @staticmethod
    def _vm_indicators() -> list[str]:
        indicators: list[str] = []
        haystack = " ".join(
            [
                platform.platform().lower(),
                platform.node().lower(),
                platform.processor().lower(),
                os.environ.get("COMPUTERNAME", "").lower(),
            ]
        )
        for keyword in VM_KEYWORDS:
            if keyword in haystack:
                indicators.append(keyword)
        return sorted(set(indicators))

    def evaluate(self) -> RuntimeGuardReport:
        report = RuntimeGuardReport()
        if not self._enabled:
            return report

        report.debugger_detected = self._is_debugger_attached()
        report.timing_anomaly = self._timing_anomaly(self._timing_threshold_ms)
        report.vm_indicators = self._vm_indicators()
        report.vm_detected = len(report.vm_indicators) > 0

        if report.debugger_detected:
            report.reasons.append("debugger_detected")
            if self._block_debugger:
                report.blocked = True

        if report.vm_detected:
            report.reasons.append("vm_detected")

        if report.timing_anomaly:
            report.reasons.append("timing_anomaly")

        return report
