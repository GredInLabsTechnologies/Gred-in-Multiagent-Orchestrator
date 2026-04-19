"""End-to-end test for GIMO Mesh lifecycle.

Exercises the full flow:
  1. Registry: enrollment, state machine, heartbeat, thermal lockout
  2. Enrollment tokens: create, claim, anti-replay, expiry, revoke
  3. Telemetry: thermal profiles, health scores, duty cycle
  4. Dispatch: device selection, thermal pre-check, quantization
  5. Audit: record, query, receipt correlation
  6. PlanDecomposer: action classification, target types, complexity
  7. Model: can_execute bilateral consent
  8. Full lifecycle integration test
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from tools.gimo_server.models.mesh import (
    ConnectionState,
    DeviceMode,
    HeartbeatPayload,
    MeshDeviceInfo,
    OperationalState,
    TaskFingerprint,
    ThermalEvent,
)
from tools.gimo_server.services.mesh import audit as audit_mod
from tools.gimo_server.services.mesh import enrollment as enrollment_mod
from tools.gimo_server.services.mesh import registry as registry_mod
from tools.gimo_server.services.mesh import telemetry as telemetry_mod
from tools.gimo_server.services.mesh.audit import MeshAuditService
from tools.gimo_server.services.mesh.decomposer import PlanDecomposer
from tools.gimo_server.services.mesh.dispatch import DispatchService
from tools.gimo_server.services.mesh.enrollment import EnrollmentService
from tools.gimo_server.services.mesh.host_bootstrap import (
    AndroidHostBootstrapConfig,
    AndroidHostBootstrapService,
)
from tools.gimo_server.services.mesh.registry import MeshRegistry
from tools.gimo_server.services.mesh.telemetry import TelemetryService


@pytest.fixture()
def mesh_tmpdir() -> Generator[Path, None, None]:
    d = Path(tempfile.mkdtemp(prefix="mesh_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def registry(mesh_tmpdir: Path, monkeypatch: pytest.MonkeyPatch) -> MeshRegistry:
    monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", mesh_tmpdir)
    monkeypatch.setattr(MeshRegistry, "MESH_DIR", mesh_tmpdir / "mesh")
    monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", mesh_tmpdir / "mesh" / "devices")
    monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", mesh_tmpdir / "mesh" / "tokens")
    monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", mesh_tmpdir / "mesh" / "thermal_events.jsonl")
    monkeypatch.setattr(MeshRegistry, "LOCK_FILE", mesh_tmpdir / "mesh" / ".mesh.lock")
    return MeshRegistry()


@pytest.fixture()
def enrollment_svc(registry: MeshRegistry, mesh_tmpdir: Path, monkeypatch: pytest.MonkeyPatch) -> EnrollmentService:
    monkeypatch.setattr(enrollment_mod, "_MESH_DIR", mesh_tmpdir / "mesh")
    monkeypatch.setattr(enrollment_mod, "_TOKENS_DIR", mesh_tmpdir / "mesh" / "tokens")
    monkeypatch.setattr(enrollment_mod, "_LOCK_FILE", mesh_tmpdir / "mesh" / ".enrollment.lock")
    return EnrollmentService(registry)


@pytest.fixture()
def telemetry(mesh_tmpdir: Path, monkeypatch: pytest.MonkeyPatch) -> TelemetryService:
    monkeypatch.setattr(telemetry_mod, "_MESH_DIR", mesh_tmpdir / "mesh")
    monkeypatch.setattr(telemetry_mod, "_PROFILES_DIR", mesh_tmpdir / "mesh" / "thermal_profiles")
    monkeypatch.setattr(telemetry_mod, "_LOCK_FILE", mesh_tmpdir / "mesh" / ".telemetry.lock")
    # Reset singleton so each test gets a fresh instance with patched paths
    monkeypatch.setattr(telemetry_mod, "_singleton_instance", None)
    svc = TelemetryService()
    svc._initialized = False
    svc.__init__()
    return svc


@pytest.fixture()
def audit(mesh_tmpdir: Path, monkeypatch: pytest.MonkeyPatch) -> MeshAuditService:
    monkeypatch.setattr(audit_mod, "_MESH_DIR", mesh_tmpdir / "mesh")
    monkeypatch.setattr(audit_mod, "_AUDIT_LOG", mesh_tmpdir / "mesh" / "audit.jsonl")
    monkeypatch.setattr(audit_mod, "_LOCK_FILE", mesh_tmpdir / "mesh" / ".audit.lock")
    return MeshAuditService()


def _get_secret(registry: MeshRegistry, device_id: str) -> str:
    """Get device_secret from enrolled device."""
    device = registry.get_device(device_id)
    return device.device_secret if device else ""


# ── 1. Registry: enrollment + state machine ─────────────────

class TestRegistryLifecycle:
    def test_enroll_device(self, registry: MeshRegistry):
        device = registry.enroll_device("phone-01", name="Mi Pixel", device_class="mobile")
        assert device.device_id == "phone-01"
        assert device.name == "Mi Pixel"
        assert device.connection_state == ConnectionState.pending_approval
        assert device.device_secret  # Secret should be auto-generated

    def test_approve_device(self, registry: MeshRegistry):
        registry.enroll_device("phone-01")
        device = registry.approve_device("phone-01")
        assert device.connection_state == ConnectionState.approved

    def test_refuse_device(self, registry: MeshRegistry):
        registry.enroll_device("phone-01")
        device = registry.refuse_device("phone-01")
        assert device.connection_state == ConnectionState.refused

    def test_invalid_transition_raises(self, registry: MeshRegistry):
        registry.enroll_device("phone-01")
        with pytest.raises(ValueError, match="Invalid transition"):
            registry.set_connection_state("phone-01", ConnectionState.connected)

    def test_heartbeat_auto_connects(self, registry: MeshRegistry):
        registry.enroll_device("phone-01")
        registry.approve_device("phone-01")
        secret = _get_secret(registry, "phone-01")
        payload = HeartbeatPayload(
            device_id="phone-01",
            device_secret=secret,
            cpu_temp_c=55.0,
            gpu_temp_c=60.0,
            battery_percent=85.0,
            cpu_percent=30.0,
            ram_percent=45.0,
            soc_model="Tensor G4",
            soc_vendor="Google",
        )
        device = registry.process_heartbeat(payload)
        assert device.connection_state == ConnectionState.connected
        assert device.soc_model == "Tensor G4"
        assert device.soc_vendor == "Google"

    def test_heartbeat_wrong_secret_rejected(self, registry: MeshRegistry):
        registry.enroll_device("phone-01")
        registry.approve_device("phone-01")
        payload = HeartbeatPayload(
            device_id="phone-01",
            device_secret="wrong-secret",
            cpu_temp_c=55.0,
        )
        with pytest.raises(ValueError, match="Invalid device_secret"):
            registry.process_heartbeat(payload)

    def test_heartbeat_thermal_lockout(self, registry: MeshRegistry):
        registry.enroll_device("phone-01")
        registry.approve_device("phone-01")
        secret = _get_secret(registry, "phone-01")
        payload = HeartbeatPayload(
            device_id="phone-01",
            device_secret=secret,
            thermal_locked_out=True,
            cpu_temp_c=98.0,
        )
        device = registry.process_heartbeat(payload)
        assert device.connection_state == ConnectionState.thermal_lockout
        assert device.operational_state == OperationalState.locked_out
        assert device.model_loaded == ""

    def test_list_and_remove(self, registry: MeshRegistry):
        registry.enroll_device("phone-01")
        registry.enroll_device("laptop-02")
        assert len(registry.list_devices()) == 2
        registry.remove_device("phone-01")
        assert len(registry.list_devices()) == 1

    def test_eligible_devices(self, registry: MeshRegistry):
        registry.enroll_device("phone-01")
        registry.approve_device("phone-01")
        eligible = registry.get_eligible_devices(mesh_enabled=True)
        assert len(eligible) == 1
        assert len(registry.get_eligible_devices(mesh_enabled=False)) == 0

    def test_mesh_status(self, registry: MeshRegistry):
        registry.enroll_device("phone-01", device_mode=DeviceMode.inference)
        registry.enroll_device("laptop-02", device_mode=DeviceMode.hybrid)
        registry.approve_device("phone-01")
        status = registry.get_status(mesh_enabled=True)
        assert status.device_count == 2
        assert status.devices_connected == 1
        assert status.devices_by_mode["inference"] == 1
        assert status.devices_by_mode["hybrid"] == 1


class TestAndroidHostBootstrap:
    def test_bootstrap_registers_host_device(self, registry: MeshRegistry):
        service = AndroidHostBootstrapService(registry)
        device = service.bootstrap(
            AndroidHostBootstrapConfig(
                enabled=True,
                device_id="phone-host",
                device_name="Galaxy Host",
                device_mode=DeviceMode.server,
                device_class="smartphone",
                inference_endpoint="",
            )
        )

        assert device.device_id == "phone-host"
        assert device.connection_state == ConnectionState.connected
        assert device.device_mode == DeviceMode.server
        assert service.runtime_path.exists()
        runtime_text = service.runtime_path.read_text(encoding="utf-8")
        assert '"device_id": "phone-host"' in runtime_text
        assert '"device_mode": "server"' in runtime_text

    def test_bootstrap_updates_existing_host_device(self, registry: MeshRegistry):
        registry.enroll_device("phone-host", name="Old Name", device_mode=DeviceMode.inference)
        service = AndroidHostBootstrapService(registry)

        updated = service.bootstrap(
            AndroidHostBootstrapConfig(
                enabled=True,
                device_id="phone-host",
                device_name="Galaxy Host",
                device_mode=DeviceMode.hybrid,
                device_class="smartphone",
                inference_endpoint="http://192.168.0.24:8080",
            )
        )

        assert updated.name == "Galaxy Host"
        assert updated.device_mode == DeviceMode.hybrid
        assert updated.connection_state == ConnectionState.connected
        assert updated.inference_endpoint == "http://192.168.0.24:8080"


# ── 2. Enrollment tokens ────────────────────────────────────

class TestEnrollment:
    def test_create_and_claim_token(self, enrollment_svc: EnrollmentService):
        token = enrollment_svc.create_token(ttl_minutes=5)
        assert token.token
        assert not token.used
        device = enrollment_svc.claim(
            token_str=token.token, device_id="phone-01",
        )
        assert device.connection_state == ConnectionState.pending_approval

    def test_double_claim_rejected(self, enrollment_svc: EnrollmentService):
        token = enrollment_svc.create_token()
        enrollment_svc.claim(token_str=token.token, device_id="phone-01")
        with pytest.raises(ValueError, match="already used"):
            enrollment_svc.claim(token_str=token.token, device_id="phone-02")

    def test_expired_token_rejected(self, enrollment_svc: EnrollmentService):
        token = enrollment_svc.create_token(ttl_minutes=0)
        with pytest.raises(ValueError, match="expired"):
            enrollment_svc.claim(token_str=token.token, device_id="phone-01")

    def test_revoke_token(self, enrollment_svc: EnrollmentService):
        token = enrollment_svc.create_token()
        assert enrollment_svc.revoke_token(token.token)
        with pytest.raises(ValueError, match="Invalid"):
            enrollment_svc.claim(token_str=token.token, device_id="phone-01")

    def test_list_tokens(self, enrollment_svc: EnrollmentService):
        enrollment_svc.create_token()
        enrollment_svc.create_token()
        tokens = enrollment_svc.list_tokens()
        assert len(tokens) == 2

    def test_duplicate_device_rejected(self, enrollment_svc: EnrollmentService):
        t1 = enrollment_svc.create_token()
        t2 = enrollment_svc.create_token()
        enrollment_svc.claim(token_str=t1.token, device_id="phone-01")
        with pytest.raises(ValueError, match="already enrolled"):
            enrollment_svc.claim(token_str=t2.token, device_id="phone-01")


# ── 3. Telemetry + thermal profiles ─────────────────────────

class TestTelemetry:
    def test_ingest_warning(self, telemetry: TelemetryService):
        event = ThermalEvent(
            device_id="phone-01",
            event_type="warning",
            trigger_sensor="cpu",
            trigger_value=78.0,
            trigger_threshold=75.0,
        )
        profile = telemetry.ingest_thermal_event(event)
        assert profile.total_events == 1
        assert profile.warnings == 1
        assert profile.health_score == 99.5

    def test_ingest_throttle_updates_duty_cycle(self, telemetry: TelemetryService):
        event = ThermalEvent(
            device_id="phone-01",
            event_type="throttle",
            trigger_sensor="cpu",
            trigger_value=88.0,
            trigger_threshold=85.0,
            duration_before_trigger_minutes=20.0,
        )
        profile = telemetry.ingest_thermal_event(event)
        assert profile.throttles == 1
        assert profile.recommended_duty_cycle_min == 16.0
        assert profile.health_score == 98.0

    def test_ingest_lockout(self, telemetry: TelemetryService):
        event = ThermalEvent(
            device_id="phone-01",
            event_type="lockout",
            trigger_sensor="gpu",
            trigger_value=96.0,
            trigger_threshold=95.0,
        )
        profile = telemetry.ingest_thermal_event(event)
        assert profile.lockouts == 1
        assert profile.health_score == 95.0
        assert profile.worst_gpu_temp == 96.0

    def test_cumulative_health_degradation(self, telemetry: TelemetryService):
        for i in range(5):
            telemetry.ingest_thermal_event(ThermalEvent(
                device_id="phone-01",
                event_type="warning",
                trigger_sensor="cpu",
                trigger_value=76.0 + i,
                trigger_threshold=75.0,
            ))
        for i in range(3):
            telemetry.ingest_thermal_event(ThermalEvent(
                device_id="phone-01",
                event_type="throttle",
                trigger_sensor="cpu",
                trigger_value=86.0 + i,
                trigger_threshold=85.0,
                duration_before_trigger_minutes=15.0,
            ))
        profile = telemetry.get_profile("phone-01")
        assert profile.health_score == 91.5
        assert profile.worst_cpu_temp == 88.0

    def test_profile_persistence(self, telemetry: TelemetryService):
        telemetry.ingest_thermal_event(ThermalEvent(
            device_id="phone-01",
            event_type="throttle",
            trigger_sensor="cpu",
            trigger_value=87.0,
            trigger_threshold=85.0,
            duration_before_trigger_minutes=25.0,
        ))
        profile = telemetry.get_profile("phone-01")
        assert profile.throttles == 1
        assert profile.worst_cpu_temp == 87.0

    def test_list_profiles(self, telemetry: TelemetryService):
        for did in ["phone-01", "laptop-02", "pi-03"]:
            telemetry.ingest_thermal_event(ThermalEvent(
                device_id=did,
                event_type="warning",
                trigger_sensor="cpu",
                trigger_value=76.0,
                trigger_threshold=75.0,
            ))
        profiles = telemetry.list_profiles()
        assert len(profiles) == 3


# ── 4. Dispatch ─────────────────────────────────────────────

class TestDispatch:
    def _connect_device(
        self, registry: MeshRegistry, device_id: str, **kwargs
    ) -> MeshDeviceInfo:
        registry.enroll_device(device_id)
        registry.approve_device(device_id)
        secret = _get_secret(registry, device_id)
        defaults = dict(
            device_id=device_id,
            device_secret=secret,
            cpu_temp_c=50.0,
            gpu_temp_c=55.0,
            battery_percent=80.0,
            cpu_percent=25.0,
            ram_percent=40.0,
            health_score=95.0,
            model_loaded="llama3.2:3b-q4",
        )
        defaults.update(kwargs)
        return registry.process_heartbeat(HeartbeatPayload(**defaults))

    def test_dispatch_selects_best_device(self, registry: MeshRegistry):
        self._connect_device(registry, "phone-01", health_score=90.0)
        self._connect_device(registry, "laptop-02", health_score=99.0, cpu_percent=10.0)
        dispatch = DispatchService(registry)
        fp = TaskFingerprint(action_class="code_generation", estimated_complexity="simple")
        decision = dispatch.dispatch(fp, mesh_enabled=True)
        assert decision.device_id == "laptop-02"
        assert not decision.fallback_to_local

    def test_dispatch_fallback_when_disabled(self, registry: MeshRegistry):
        self._connect_device(registry, "phone-01")
        dispatch = DispatchService(registry)
        fp = TaskFingerprint(action_class="analysis")
        decision = dispatch.dispatch(fp, mesh_enabled=False)
        assert decision.fallback_to_local

    def test_dispatch_fallback_no_devices(self, registry: MeshRegistry):
        dispatch = DispatchService(registry)
        fp = TaskFingerprint(action_class="analysis")
        decision = dispatch.dispatch(fp, mesh_enabled=True)
        assert decision.fallback_to_local

    def test_thermal_precheck_filters_hot_devices(self, registry: MeshRegistry):
        self._connect_device(
            registry, "hot-phone",
            cpu_temp_c=70.0, gpu_temp_c=75.0, health_score=95.0,
        )
        self._connect_device(
            registry, "cool-laptop",
            cpu_temp_c=45.0, gpu_temp_c=50.0, health_score=90.0,
        )
        dispatch = DispatchService(registry)
        fp = TaskFingerprint(action_class="inference")
        decision = dispatch.dispatch(fp, mesh_enabled=True)
        assert decision.device_id == "cool-laptop"

    def test_all_devices_hot_fallback(self, registry: MeshRegistry):
        self._connect_device(registry, "hot-1", cpu_temp_c=70.0, gpu_temp_c=75.0)
        self._connect_device(registry, "hot-2", cpu_temp_c=68.0, gpu_temp_c=72.0)
        dispatch = DispatchService(registry)
        fp = TaskFingerprint(action_class="inference")
        decision = dispatch.dispatch(fp, mesh_enabled=True)
        assert decision.fallback_to_local
        assert not decision.thermal_headroom_ok

    def test_quantization_suggestion(self, registry: MeshRegistry):
        dispatch = DispatchService(registry)
        cool = MeshDeviceInfo(device_id="c", cpu_temp_c=50.0, gpu_temp_c=55.0, battery_temp_c=30.0, ram_percent=60.0)
        hot = MeshDeviceInfo(device_id="h", cpu_temp_c=75.0, gpu_temp_c=80.0, battery_temp_c=40.0, ram_percent=50.0)
        assert dispatch.suggest_quantization(cool) == "Q8_0"
        assert dispatch.suggest_quantization(hot) == "Q4_K_M"

    def test_locked_out_device_not_eligible(self, registry: MeshRegistry):
        self._connect_device(registry, "phone-01")
        secret = _get_secret(registry, "phone-01")
        registry.process_heartbeat(HeartbeatPayload(
            device_id="phone-01", device_secret=secret,
            thermal_locked_out=True, cpu_temp_c=98.0,
        ))
        dispatch = DispatchService(registry)
        fp = TaskFingerprint(action_class="inference")
        decision = dispatch.dispatch(fp, mesh_enabled=True)
        assert decision.fallback_to_local


# ── 5. Audit ────────────────────────────────────────────────

class TestAudit:
    def test_record_and_query(self, audit: MeshAuditService):
        audit.record("enrollment", "enroll", device_id="phone-01", actor="admin")
        audit.record("connection", "approve", device_id="phone-01", actor="admin")
        audit.record("dispatch", "assign", device_id="phone-01", task_id="task-001")
        assert len(audit.query()) == 3

    def test_query_by_category(self, audit: MeshAuditService):
        audit.record("enrollment", "enroll", device_id="phone-01")
        audit.record("dispatch", "assign", device_id="phone-01")
        audit.record("thermal", "warning", device_id="phone-01")
        entries = audit.query(category="thermal")
        assert len(entries) == 1
        assert entries[0]["action"] == "warning"

    def test_query_by_device(self, audit: MeshAuditService):
        audit.record("enrollment", "enroll", device_id="phone-01")
        audit.record("enrollment", "enroll", device_id="laptop-02")
        assert len(audit.query(device_id="laptop-02")) == 1

    def test_receipt_correlation(self, audit: MeshAuditService):
        audit.record("dispatch", "assign", receipt_id="rcpt-123", task_id="task-001")
        audit.record("execution", "start", receipt_id="rcpt-123", task_id="task-001")
        audit.record("execution", "complete", receipt_id="rcpt-123", task_id="task-001")
        audit.record("dispatch", "assign", receipt_id="rcpt-456", task_id="task-002")
        correlated = audit.correlate_receipt("rcpt-123")
        assert len(correlated) == 3
        assert all(e["receipt_id"] == "rcpt-123" for e in correlated)


# ── 6. PlanDecomposer ───────────────────────────────────────

class TestDecomposer:
    def test_classify_action(self):
        decomposer = PlanDecomposer()
        steps = [
            {"action": "Write a Python function to parse JSON"},
            {"action": "Review the authentication module"},
            {"action": "Run pytest on the mesh module"},
            {"action": "Search for all TODO comments"},
            {"action": "Analyze the performance bottleneck"},
        ]
        fps = decomposer.decompose(steps)
        assert fps[0].action_class == "code_generation"
        assert fps[1].action_class == "code_review"
        assert fps[2].action_class == "test_execution"
        assert fps[3].action_class == "search"
        assert fps[4].action_class == "analysis"

    def test_detect_target_type(self):
        decomposer = PlanDecomposer()
        fps = decomposer.decompose([
            {"action": "Edit main.py to add the new endpoint"},
            {"action": "Update config.yaml with mesh settings"},
        ])
        assert fps[0].target_type == "python_file"
        assert fps[1].target_type == "config"

    def test_read_only_detection(self):
        decomposer = PlanDecomposer()
        fps = decomposer.decompose([
            {"action": "Read the configuration file"},
            {"action": "Write new test cases"},
            {"action": "Search for the error pattern"},
        ])
        assert fps[0].read_only is True
        assert fps[1].read_only is False
        assert fps[2].read_only is True

    def test_complexity_estimation(self):
        decomposer = PlanDecomposer()
        fps = decomposer.decompose([
            {"action": "fix"},  # 1 word → trivial
            {"action": "Add a new validation check for the enrollment token expiry and verify"},  # >15 words with "and"
            {"action": ("Refactor the entire dispatch service and also update the thermal "
                        "protection module and then verify all tests pass correctly now")},
        ])
        assert fps[0].estimated_complexity == "trivial"
        # "and" triggers complex for longer text
        assert fps[2].estimated_complexity in ("moderate", "complex")

    def test_domain_hints(self):
        decomposer = PlanDecomposer()
        fps = decomposer.decompose([
            {"action": "Update the mesh thermal service for the API auth endpoint"},
        ])
        hints = fps[0].domain_hints
        assert "mesh" in hints
        assert "thermal" in hints
        assert "api" in hints
        assert "auth" in hints


# ── 7. Model can_execute ────────────────────────────────────

class TestCanExecute:
    def test_connected_and_enabled(self):
        device = MeshDeviceInfo(
            device_id="phone-01",
            connection_state=ConnectionState.connected,
            operational_state=OperationalState.idle,
        )
        assert device.can_execute(mesh_enabled=True)
        assert not device.can_execute(mesh_enabled=False)

    def test_locked_out_cannot_execute(self):
        device = MeshDeviceInfo(
            device_id="phone-01",
            connection_state=ConnectionState.thermal_lockout,
            operational_state=OperationalState.locked_out,
            thermal_locked_out=True,
        )
        assert not device.can_execute(mesh_enabled=True)

    def test_local_refusal_overrides(self):
        device = MeshDeviceInfo(
            device_id="phone-01",
            connection_state=ConnectionState.connected,
            local_allow_task_execution=False,
        )
        assert not device.can_execute(mesh_enabled=True)

    def test_disabled_state_blocks(self):
        device = MeshDeviceInfo(
            device_id="phone-01",
            connection_state=ConnectionState.connected,
            operational_state=OperationalState.disabled,
        )
        assert not device.can_execute(mesh_enabled=True)


# ── 8. Full lifecycle integration ────────────────────────────

class TestFullLifecycle:
    def test_full_mesh_lifecycle(
        self,
        registry: MeshRegistry,
        enrollment_svc: EnrollmentService,
        telemetry: TelemetryService,
        audit: MeshAuditService,
    ):
        # 1: Create enrollment token
        token = enrollment_svc.create_token(ttl_minutes=10)
        assert token.token

        # 2: Device claims token
        device = enrollment_svc.claim(
            token_str=token.token, device_id="pixel-7", name="Shilo's Pixel",
        )
        assert device.connection_state == ConnectionState.pending_approval
        audit.record("enrollment", "claim", device_id="pixel-7")

        # 3: Admin approves
        device = registry.approve_device("pixel-7")
        assert device.connection_state == ConnectionState.approved
        audit.record("connection", "approve", device_id="pixel-7", actor="admin")

        # 4: Heartbeat → auto-connect
        secret = _get_secret(registry, "pixel-7")
        device = registry.process_heartbeat(HeartbeatPayload(
            device_id="pixel-7",
            device_secret=secret,
            soc_model="Tensor G4",
            soc_vendor="Google",
            max_model_params_b=3.0,
            model_loaded="llama3.2:3b-q4",
            cpu_temp_c=52.0,
            gpu_temp_c=58.0,
            battery_percent=78.0,
            cpu_percent=20.0,
            ram_percent=55.0,
        ))
        assert device.connection_state == ConnectionState.connected
        assert device.model_loaded == "llama3.2:3b-q4"

        # 5: Device is eligible
        eligible = registry.get_eligible_devices(mesh_enabled=True)
        assert len(eligible) == 1
        assert eligible[0].device_id == "pixel-7"

        # 6: Dispatch task
        dispatch = DispatchService(registry)
        fp = TaskFingerprint(
            action_class="code_generation",
            target_type="python_file",
            estimated_complexity="simple",
        )
        decision = dispatch.dispatch(fp, mesh_enabled=True)
        assert decision.device_id == "pixel-7"
        assert not decision.fallback_to_local
        audit.record("dispatch", "assign", device_id="pixel-7", task_id="task-001", receipt_id="rcpt-001")

        # 7: Thermal warning
        profile = telemetry.ingest_thermal_event(ThermalEvent(
            device_id="pixel-7",
            event_type="warning",
            trigger_sensor="cpu",
            trigger_value=78.0,
            trigger_threshold=75.0,
            task_id="task-001",
        ))
        assert profile.warnings == 1
        assert profile.health_score == 99.5
        audit.record("thermal", "warning", device_id="pixel-7", task_id="task-001")

        # 8: Thermal throttle
        profile = telemetry.ingest_thermal_event(ThermalEvent(
            device_id="pixel-7",
            event_type="throttle",
            trigger_sensor="cpu",
            trigger_value=87.0,
            trigger_threshold=85.0,
            duration_before_trigger_minutes=18.0,
            task_id="task-001",
        ))
        assert profile.throttles == 1
        assert profile.recommended_duty_cycle_min == 14.4
        assert profile.health_score == 97.5

        # 9: Audit trail
        # BUGS_LATENTES §H9 fix (2026-04-17): DispatchService ahora audita cada
        # decision automáticamente (action="routed"), además del manual
        # "dispatch/assign" que emite este test. Total 5 entries.
        all_entries = audit.query(device_id="pixel-7")
        assert len(all_entries) == 5  # claim, approve, dispatch/routed (H9), dispatch/assign, thermal warning
        dispatch_entries = [e for e in all_entries if e["category"] == "dispatch"]
        assert {e["action"] for e in dispatch_entries} == {"routed", "assign"}

        # 10: Quantization
        assert dispatch.suggest_quantization(device) == "Q8_0"

        # 11: Lockout
        registry.process_heartbeat(HeartbeatPayload(
            device_id="pixel-7",
            device_secret=secret,
            thermal_locked_out=True,
            cpu_temp_c=97.0,
        ))
        locked = registry.get_device("pixel-7")
        assert locked.connection_state == ConnectionState.thermal_lockout
        assert locked.operational_state == OperationalState.locked_out
        assert len(registry.get_eligible_devices(mesh_enabled=True)) == 0

        # 12: Cleanup
        assert registry.remove_device("pixel-7")
        assert registry.get_device("pixel-7") is None
