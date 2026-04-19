"""Tests for mesh → ObservabilityService bridge.

Verifies that mesh events (enrollment, state change, thermal, dispatch)
emit spans to the observability dashboard.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Generator, List

import pytest

from tools.gimo_server.models.mesh import (
    ConnectionState,
    HeartbeatPayload,
    TaskFingerprint,
    ThermalEvent,
)
from tools.gimo_server.services.mesh import observability as mesh_obs
from tools.gimo_server.services.mesh import registry as registry_mod
from tools.gimo_server.services.mesh.dispatch import DispatchService
from tools.gimo_server.services.mesh.registry import MeshRegistry


@pytest.fixture()
def captured_spans(monkeypatch: pytest.MonkeyPatch) -> List[dict]:
    """Capture every record_span invocation from the mesh bridge."""
    spans: List[dict] = []

    def _fake_emit(name: str, attributes: dict) -> None:
        spans.append({"name": name, **attributes})

    monkeypatch.setattr(mesh_obs, "_emit", _fake_emit)
    return spans


@pytest.fixture()
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MeshRegistry:
    monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", tmp_path)
    monkeypatch.setattr(MeshRegistry, "MESH_DIR", tmp_path / "mesh")
    monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", tmp_path / "mesh" / "devices")
    monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", tmp_path / "mesh" / "tokens")
    monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", tmp_path / "mesh" / "thermal_events.jsonl")
    monkeypatch.setattr(MeshRegistry, "LOCK_FILE", tmp_path / "mesh" / ".mesh.lock")
    return MeshRegistry()


class TestEnrollmentBridge:
    def test_enroll_emits_span(self, registry: MeshRegistry, captured_spans: List[dict]):
        registry.enroll_device("phone-01", device_class="mobile")
        names = [s["name"] for s in captured_spans]
        assert "enroll" in names
        enroll = next(s for s in captured_spans if s["name"] == "enroll")
        assert enroll["device_id"] == "phone-01"
        assert enroll["device_class"] == "mobile"
        assert enroll["status"] == "ok"


class TestStateChangeBridge:
    def test_approve_emits_state_change_span(self, registry: MeshRegistry, captured_spans: List[dict]):
        registry.enroll_device("phone-01")
        captured_spans.clear()  # Ignore the enrollment span
        registry.approve_device("phone-01")
        state_changes = [s for s in captured_spans if s["name"] == "state_change"]
        assert len(state_changes) == 1
        assert state_changes[0]["old_state"] == "pending_approval"
        assert state_changes[0]["new_state"] == "approved"


class TestThermalBridge:
    def test_thermal_warning_emits_span(self, registry: MeshRegistry, captured_spans: List[dict]):
        registry.record_thermal_event(ThermalEvent(
            device_id="phone-01",
            event_type="warning",
            trigger_sensor="cpu",
            trigger_value=78.0,
            trigger_threshold=75.0,
        ))
        thermal = [s for s in captured_spans if s["name"] == "thermal"]
        assert len(thermal) == 1
        assert thermal[0]["event_type"] == "warning"
        assert thermal[0]["status"] == "ok"

    def test_thermal_lockout_emits_failed_status(self, registry: MeshRegistry, captured_spans: List[dict]):
        registry.record_thermal_event(ThermalEvent(
            device_id="phone-01",
            event_type="lockout",
            trigger_sensor="gpu",
            trigger_value=96.0,
            trigger_threshold=95.0,
        ))
        thermal = [s for s in captured_spans if s["name"] == "thermal"]
        assert thermal[0]["status"] == "failed"


class TestDispatchBridge:
    def test_dispatch_emits_span_with_fallback(self, registry: MeshRegistry, captured_spans: List[dict]):
        dispatch = DispatchService(registry)
        fp = TaskFingerprint(action_class="analysis")
        dispatch.dispatch(fp, mesh_enabled=True)
        span = next(s for s in captured_spans if s["name"] == "dispatch")
        assert span["fallback_to_local"] is True
        assert span["action_class"] == "analysis"

    def test_dispatch_emits_span_with_selected_device(self, registry: MeshRegistry, captured_spans: List[dict]):
        # Enroll + connect a device
        registry.enroll_device("phone-01")
        registry.approve_device("phone-01")
        secret = registry.get_device("phone-01").device_secret
        registry.process_heartbeat(HeartbeatPayload(
            device_id="phone-01",
            device_secret=secret,
            cpu_temp_c=50.0, gpu_temp_c=55.0,
            battery_percent=80.0,
            cpu_percent=25.0, ram_percent=40.0,
            health_score=95.0,
            model_loaded="llama3.2:3b-q4",
        ))
        captured_spans.clear()

        dispatch = DispatchService(registry)
        fp = TaskFingerprint(action_class="code_generation")
        dispatch.dispatch(fp, mesh_enabled=True)

        span = next(s for s in captured_spans if s["name"] == "dispatch")
        assert span["device_id"] == "phone-01"
        assert span["fallback_to_local"] is False
        assert span["action_class"] == "code_generation"
        assert span["health_score"] > 0


class TestBestEffortSemantics:
    def test_emit_never_raises_when_observability_broken(self, monkeypatch: pytest.MonkeyPatch):
        """Bridge must swallow exceptions so mesh logic never breaks."""
        # Force the import inside _emit to fail
        import sys
        bogus = object()
        # Monkey-patch ObservabilityService.record_span to raise
        from tools.gimo_server.services.observability_pkg.observability_service import ObservabilityService

        def _boom(*args, **kwargs):
            raise RuntimeError("observability is down")

        monkeypatch.setattr(ObservabilityService, "record_span", classmethod(lambda cls, *a, **kw: _boom()))

        # Should not raise
        mesh_obs.emit_enrollment("phone-01", "inference", "mobile")
        mesh_obs.emit_state_change("phone-01", "pending_approval", "approved")
        mesh_obs.emit_thermal("phone-01", "warning", "cpu", 78.0, 75.0)
        mesh_obs.emit_dispatch("phone-01", "ok", False, 95.0, "code_generation")


class TestSpansReachObservabilityService:
    """Integration-level: without mocks, spans land in ObservabilityService._ui_spans."""

    def test_enroll_span_persists_in_observability_store(
        self, registry: MeshRegistry, monkeypatch: pytest.MonkeyPatch
    ):
        from tools.gimo_server.services.observability_pkg.observability_service import ObservabilityService

        # Reset to isolate this test
        ObservabilityService.reset()
        registry.enroll_device("phone-iso", device_class="mobile")

        # Pull UI spans and assert mesh event is there
        spans = ObservabilityService._ui_spans  # noqa: SLF001 — test-only access
        mesh_spans = [s for s in spans if s.get("kind") == "mesh"]
        assert any(s.get("name") == "enroll" and s.get("device_id") == "phone-iso"
                   for s in mesh_spans)
