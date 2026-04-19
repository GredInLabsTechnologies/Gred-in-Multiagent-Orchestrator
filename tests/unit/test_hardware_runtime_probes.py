"""BUGS_LATENTES §H12 — tests del probe dinámico de runtimes.

Verifican:
- ``_probe_python_native()`` devuelve True en el propio ambiente (GIMO corre)
- ``_probe_wasm()`` maneja correctamente ausencia de wasmtime/wasmer
- Cache TTL funciona (no re-probe en segunda llamada inmediata)
- ``HardwareSnapshot.supported_runtimes`` llega populado al dataclass
- El campo también aparece en ``DeviceCapabilities`` vía Pydantic
"""
from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

from tools.gimo_server.services import hardware_monitor_service as hm_service
from tools.gimo_server.services.hardware_monitor_service import (
    HardwareMonitorService,
    HardwareSnapshot,
    _invalidate_runtimes_cache,
    _probe_python_native,
    _probe_supported_runtimes,
    _probe_wasm,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Cache limpia antes/después de cada test."""
    _invalidate_runtimes_cache()
    yield
    _invalidate_runtimes_cache()


def test_python_native_probe_true_in_gimo_env():
    """Si estos tests corren, CPython funciona — el probe debe confirmarlo."""
    assert _probe_python_native() is True


def test_wasm_probe_returns_false_when_no_runtime():
    """Sin wasmtime/wasmer CLI ni library: returns False."""
    def fake_run(args, **kw):
        raise FileNotFoundError(f"no such file: {args[0]}")

    with patch.object(hm_service.subprocess, "run", side_effect=fake_run):
        with patch.dict("sys.modules", {"wasmtime": None}):
            # Con wasmtime mocked a None, importlib.import_module lanza ImportError
            result = _probe_wasm()
    assert result is False


def test_wasm_probe_returns_true_when_cli_ok():
    """Si wasmtime CLI exit 0, el probe devuelve True."""
    class _Result:
        returncode = 0
        stdout = b"wasmtime 28.0.0\n"
        stderr = b""

    def fake_run(args, **kw):
        if args[0] == "wasmtime":
            return _Result()
        raise FileNotFoundError()

    with patch.object(hm_service.subprocess, "run", side_effect=fake_run):
        assert _probe_wasm() is True


def test_supported_runtimes_caches_within_ttl():
    """Segunda llamada dentro del TTL reusa cache (no re-probe)."""
    call_count = {"python": 0, "wasm": 0}

    def fake_python_probe() -> bool:
        call_count["python"] += 1
        return True

    def fake_wasm_probe() -> bool:
        call_count["wasm"] += 1
        return False

    with patch.object(hm_service, "_probe_python_native", fake_python_probe):
        with patch.object(hm_service, "_probe_wasm", fake_wasm_probe):
            first = _probe_supported_runtimes()
            second = _probe_supported_runtimes()

    assert first == second == ["python_native"]
    # Cada probe se llamó solo UNA vez — la segunda es cache hit
    assert call_count["python"] == 1
    assert call_count["wasm"] == 1


def test_cache_invalidation_forces_reprobe():
    """_invalidate_runtimes_cache fuerza re-probe."""
    call_count = {"n": 0}

    def counting_probe() -> bool:
        call_count["n"] += 1
        return True

    with patch.object(hm_service, "_probe_python_native", counting_probe):
        with patch.object(hm_service, "_probe_wasm", lambda: False):
            _probe_supported_runtimes()
            _invalidate_runtimes_cache()
            _probe_supported_runtimes()

    assert call_count["n"] == 2


def test_snapshot_includes_supported_runtimes():
    """HardwareSnapshot devuelto por get_snapshot incluye supported_runtimes."""
    HardwareMonitorService.reset_instance()
    svc = HardwareMonitorService.get_instance()
    snap = svc.get_snapshot()

    # Debe ser lista (no None) — default_factory=list
    assert isinstance(snap.supported_runtimes, list)
    # En cualquier dev box donde corren estos tests, python_native es cierto
    assert "python_native" in snap.supported_runtimes


def test_device_capabilities_carries_supported_runtimes():
    """DeviceCapabilities (Pydantic) acepta + serializa supported_runtimes."""
    from tools.gimo_server.models.mesh import DeviceCapabilities

    caps = DeviceCapabilities(
        arch="arm64-v8a",
        cpu_cores=8,
        ram_total_mb=12288,
        supported_runtimes=["python_native", "wasm"],
    )
    assert caps.supported_runtimes == ["python_native", "wasm"]

    # Round-trip JSON
    dumped = caps.model_dump_json()
    assert "supported_runtimes" in dumped
    restored = DeviceCapabilities.model_validate_json(dumped)
    assert restored.supported_runtimes == ["python_native", "wasm"]


def test_device_capabilities_default_empty():
    """Cuando no se reportan runtimes, default es lista vacía (no None)."""
    from tools.gimo_server.models.mesh import DeviceCapabilities

    caps = DeviceCapabilities(arch="x86_64")
    assert caps.supported_runtimes == []
    assert isinstance(caps.supported_runtimes, list)


def test_snapshot_supported_runtimes_subset_of_known():
    """Los valores emitidos están en el set conocido (no strings libres)."""
    HardwareMonitorService.reset_instance()
    svc = HardwareMonitorService.get_instance()
    snap = svc.get_snapshot()

    known = {"python_native", "wasm", "micro_c", "web"}
    for rt in snap.supported_runtimes:
        assert rt in known, f"runtime inesperado en snapshot: {rt!r}"
