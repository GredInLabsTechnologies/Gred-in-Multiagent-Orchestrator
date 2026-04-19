"""BUGS_LATENTES §H10 — thermal thresholds tunables.

Antes del fix los thresholds (65/70/35 °C) estaban hardcoded en
``_filter_thermal_headroom``. Ahora viven en ``ThermalThresholds`` dataclass
inyectable en el constructor de DispatchService o via env vars.

Defaults preservan el comportamiento histórico.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from tools.gimo_server.models.mesh import (
    ConnectionState,
    DeviceCapabilities,
    DeviceMode,
    MeshDeviceInfo,
    OperationalState,
)
from tools.gimo_server.services.mesh.dispatch import (
    DispatchService,
    ThermalThresholds,
)
from tools.gimo_server.services.mesh.registry import MeshRegistry


@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tools.gimo_server.services.mesh.registry.OPS_DATA_DIR", tmp_path
    )
    return MeshRegistry()


def _warm_device(cpu_c: float = 66.0, gpu_c: float = 71.0, bat_c: float = 36.0) -> MeshDeviceInfo:
    return MeshDeviceInfo(
        device_id="warm",
        name="warm",
        device_secret="s",
        device_mode=DeviceMode.hybrid,
        connection_state=ConnectionState.connected,
        operational_state=OperationalState.idle,
        core_enabled=True,
        local_allow_core_control=True,
        local_allow_task_execution=True,
        cpu_percent=50.0,
        ram_percent=50.0,
        cpu_temp_c=cpu_c,
        gpu_temp_c=gpu_c,
        battery_temp_c=bat_c,
        battery_percent=80.0,
        health_score=100.0,
        last_heartbeat=datetime.now(timezone.utc),
        capabilities=DeviceCapabilities(
            arch="x86_64", cpu_cores=8, ram_total_mb=16384,
        ),
    )


def test_default_thresholds_match_historic_values():
    t = ThermalThresholds()
    assert t.cpu_hot_c == 65.0
    assert t.gpu_hot_c == 70.0
    assert t.battery_hot_c == 35.0


def test_default_preserves_historic_filter_behavior(tmp_registry):
    """Con defaults, device con cpu=66 + gpu=71 queda excluido (como antes)."""
    svc = DispatchService(tmp_registry)
    d = _warm_device(cpu_c=66.0, gpu_c=71.0, bat_c=20.0)
    filtered = svc._filter_thermal_headroom([d])
    assert len(filtered) == 0  # cpu_hot + gpu_hot → skip


def test_custom_cpu_threshold_allows_warm_device(tmp_registry):
    """Con cpu_hot_c=80, un device a 66 °C ya no es 'hot'."""
    custom = ThermalThresholds(cpu_hot_c=80.0, gpu_hot_c=70.0, battery_hot_c=35.0)
    svc = DispatchService(tmp_registry, thermal_thresholds=custom)
    d = _warm_device(cpu_c=66.0, gpu_c=71.0, bat_c=20.0)
    filtered = svc._filter_thermal_headroom([d])
    # cpu_hot=False (66 < 80) → cpu_hot ∧ gpu_hot fails → passes filter
    assert len(filtered) == 1


def test_custom_battery_threshold_tightens(tmp_registry):
    """battery_hot_c=30 → device a 36 °C cae en bat_hot."""
    custom = ThermalThresholds(cpu_hot_c=65.0, gpu_hot_c=70.0, battery_hot_c=30.0)
    svc = DispatchService(tmp_registry, thermal_thresholds=custom)
    # cpu a 66 → cpu_hot=True; bat a 36 → bat_hot=True (custom)
    d = _warm_device(cpu_c=66.0, gpu_c=30.0, bat_c=36.0)
    filtered = svc._filter_thermal_headroom([d])
    # bat_hot ∧ (cpu_hot ∨ gpu_hot) → skipped
    assert len(filtered) == 0


def test_env_var_override_cpu_hot(monkeypatch):
    monkeypatch.setenv("ORCH_DISPATCH_CPU_HOT_C", "80.5")
    monkeypatch.setenv("ORCH_DISPATCH_GPU_HOT_C", "85")
    monkeypatch.delenv("ORCH_DISPATCH_BATTERY_HOT_C", raising=False)
    t = ThermalThresholds.from_env()
    assert t.cpu_hot_c == 80.5
    assert t.gpu_hot_c == 85.0
    assert t.battery_hot_c == 35.0  # default


def test_env_var_invalid_falls_back_to_default(monkeypatch):
    """Env var con valor malformado usa el default + warning."""
    monkeypatch.setenv("ORCH_DISPATCH_CPU_HOT_C", "not_a_float")
    t = ThermalThresholds.from_env()
    assert t.cpu_hot_c == 65.0


def test_thermal_throttled_flag_still_overrides(tmp_registry):
    """thermal_throttled=True excluye SIEMPRE, independiente de thresholds."""
    custom = ThermalThresholds(cpu_hot_c=200.0, gpu_hot_c=200.0, battery_hot_c=200.0)
    svc = DispatchService(tmp_registry, thermal_thresholds=custom)
    d = _warm_device(cpu_c=25.0, gpu_c=25.0, bat_c=20.0)
    d.thermal_throttled = True
    filtered = svc._filter_thermal_headroom([d])
    assert len(filtered) == 0  # safety valve no-bypassable
