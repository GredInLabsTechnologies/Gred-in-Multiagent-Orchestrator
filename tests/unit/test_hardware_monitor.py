"""Unit tests for HardwareMonitorService — singleton, load levels, thresholds, and logging."""

import json
from collections import namedtuple
from unittest.mock import patch, MagicMock

import pytest

from tools.gimo_server.services.hardware_monitor_service import (
    HardwareMonitorService,
    HardwareSnapshot,
    DEFAULT_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VirtualMemory = namedtuple("VirtualMemory", ["percent", "available", "total"])


def _make_snapshot(cpu: float = 30.0, ram: float = 40.0, gpu_vram_gb: float = 8.0, gpu_vram_free_gb: float = 4.0) -> HardwareSnapshot:
    return HardwareSnapshot(
        cpu_percent=cpu,
        ram_percent=ram,
        ram_available_gb=16.0,
        timestamp=1700000000.0,
        gpu_vram_gb=gpu_vram_gb,
        gpu_vram_free_gb=gpu_vram_free_gb,
        total_ram_gb=32.0,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the HardwareMonitorService singleton before and after each test."""
    HardwareMonitorService.reset_instance()
    yield
    HardwareMonitorService.reset_instance()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_instance_returns_same_object(self):
        a = HardwareMonitorService.get_instance()
        b = HardwareMonitorService.get_instance()
        assert a is b

    def test_reset_instance_clears_singleton(self):
        a = HardwareMonitorService.get_instance()
        HardwareMonitorService.reset_instance()
        b = HardwareMonitorService.get_instance()
        assert a is not b


# ---------------------------------------------------------------------------
# Load level detection
# ---------------------------------------------------------------------------

class TestLoadLevel:
    def test_safe_level(self):
        svc = HardwareMonitorService()
        snap = _make_snapshot(cpu=30.0, ram=40.0)
        assert svc.get_load_level(snap) == "safe"

    def test_caution_level_cpu(self):
        svc = HardwareMonitorService()
        snap = _make_snapshot(cpu=82.0, ram=50.0)
        assert svc.get_load_level(snap) == "caution"

    def test_caution_level_ram(self):
        svc = HardwareMonitorService()
        snap = _make_snapshot(cpu=50.0, ram=87.0)
        assert svc.get_load_level(snap) == "caution"

    def test_critical_level_cpu(self):
        svc = HardwareMonitorService()
        snap = _make_snapshot(cpu=95.0, ram=50.0)
        assert svc.get_load_level(snap) == "critical"

    def test_critical_level_ram(self):
        svc = HardwareMonitorService()
        snap = _make_snapshot(cpu=50.0, ram=95.0)
        assert svc.get_load_level(snap) == "critical"

    def test_critical_when_gpu_vram_exhausted(self):
        """GPU VRAM < 0.5 GB free should be critical regardless of CPU/RAM."""
        svc = HardwareMonitorService()
        snap = _make_snapshot(cpu=30.0, ram=40.0, gpu_vram_gb=8.0, gpu_vram_free_gb=0.3)
        assert svc.get_load_level(snap) == "critical"


# ---------------------------------------------------------------------------
# Custom thresholds
# ---------------------------------------------------------------------------

class TestCustomThresholds:
    def test_update_thresholds_changes_behavior(self):
        svc = HardwareMonitorService()

        # Default: cpu=82 is caution (threshold is 80)
        snap = _make_snapshot(cpu=82.0, ram=50.0)
        assert svc.get_load_level(snap) == "caution"

        # Raise caution threshold to 90 — cpu=82 should now be safe
        svc.update_thresholds({"caution": {"cpu": 90, "ram": 90}})
        assert svc.get_load_level(snap) == "safe"


# ---------------------------------------------------------------------------
# is_local_safe / should_defer_run
# ---------------------------------------------------------------------------

class TestSafetyChecks:
    def test_is_local_safe_false_when_critical(self):
        svc = HardwareMonitorService()
        svc._history.append(_make_snapshot(cpu=95.0, ram=50.0))
        assert svc.is_local_safe() is False

    def test_is_local_safe_true_when_safe(self):
        svc = HardwareMonitorService()
        svc._history.append(_make_snapshot(cpu=30.0, ram=40.0))
        assert svc.is_local_safe() is True

    def test_is_local_safe_false_caution_large_model(self):
        """Caution + model > 4 GB should be unsafe."""
        svc = HardwareMonitorService()
        svc._history.append(_make_snapshot(cpu=82.0, ram=50.0))
        assert svc.is_local_safe(model_size_gb=8.0) is False

    def test_should_defer_run_critical(self):
        svc = HardwareMonitorService()
        svc._history.append(_make_snapshot(cpu=95.0, ram=50.0))
        assert svc.should_defer_run(weight="light") is True

    def test_should_defer_run_caution_heavy(self):
        svc = HardwareMonitorService()
        svc._history.append(_make_snapshot(cpu=82.0, ram=50.0))
        assert svc.should_defer_run(weight="heavy") is True

    def test_should_defer_run_caution_medium(self):
        svc = HardwareMonitorService()
        svc._history.append(_make_snapshot(cpu=82.0, ram=50.0))
        assert svc.should_defer_run(weight="medium") is False

    def test_should_defer_run_safe(self):
        svc = HardwareMonitorService()
        svc._history.append(_make_snapshot(cpu=30.0, ram=40.0))
        assert svc.should_defer_run(weight="heavy") is False


# ---------------------------------------------------------------------------
# _on_level_change JSONL logging
# ---------------------------------------------------------------------------

class TestLevelChangeLogging:
    def test_on_level_change_writes_jsonl(self, tmp_path):
        svc = HardwareMonitorService()
        snap = _make_snapshot(cpu=95.0, ram=50.0)

        with patch("tools.gimo_server.services.hardware_monitor_service.LOG_DIR", tmp_path):
            svc._on_level_change("safe", "critical", snap)

        log_file = tmp_path / "hardware_load.jsonl"
        assert log_file.exists()

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["from"] == "safe"
        assert entry["to"] == "critical"
        assert entry["cpu"] == 95.0
        assert entry["ram"] == 50.0

    def test_on_level_change_appends_multiple_entries(self, tmp_path):
        svc = HardwareMonitorService()

        with patch("tools.gimo_server.services.hardware_monitor_service.LOG_DIR", tmp_path):
            svc._on_level_change("safe", "caution", _make_snapshot(cpu=82.0, ram=50.0))
            svc._on_level_change("caution", "critical", _make_snapshot(cpu=95.0, ram=50.0))

        log_file = tmp_path / "hardware_load.jsonl"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["to"] == "caution"
        assert json.loads(lines[1])["to"] == "critical"
