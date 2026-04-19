"""BUGS_LATENTES §H9 — dispatch decisions se persisten en audit log.

Antes del fix, las decisiones de dispatch solo emitían observability spans
(volátiles). Ahora cada dispatch escribe una entry en ``audit.jsonl`` bajo
category="dispatch" — permite reconstruir "por qué esta task fue a este
device" post-hoc.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from tools.gimo_server.models.mesh import (
    ConnectionState,
    DeviceCapabilities,
    DeviceMode,
    MeshDeviceInfo,
    OperationalState,
    TaskFingerprint,
)
from tools.gimo_server.services.mesh.dispatch import DispatchService
from tools.gimo_server.services.mesh.registry import MeshRegistry


@pytest.fixture
def audit_tmpdir(tmp_path, monkeypatch):
    """Aisla los paths module-level de registry + audit en tmpdir.

    registry.OPS_DATA_DIR se resuelve en cada instantiación (leído dentro de
    __init__). audit._MESH_DIR y audit._AUDIT_LOG son constants module-level
    evaluados al import → se monkey-patchean directamente.
    """
    mesh_dir = tmp_path / "mesh"
    audit_log = mesh_dir / "audit.jsonl"
    lock_file = mesh_dir / ".audit.lock"

    monkeypatch.setattr(
        "tools.gimo_server.services.mesh.registry.OPS_DATA_DIR", tmp_path
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.mesh.audit._MESH_DIR", mesh_dir
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.mesh.audit._AUDIT_LOG", audit_log
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.mesh.audit._LOCK_FILE", lock_file
    )
    yield tmp_path


def _make_device(device_id: str) -> MeshDeviceInfo:
    return MeshDeviceInfo(
        device_id=device_id,
        name=device_id,
        device_secret="s",
        device_mode=DeviceMode.hybrid,
        connection_state=ConnectionState.connected,
        operational_state=OperationalState.idle,
        core_enabled=True,
        local_allow_core_control=True,
        local_allow_task_execution=True,
        cpu_percent=20.0,
        ram_percent=30.0,
        cpu_temp_c=40.0,
        battery_percent=80.0,
        battery_charging=True,
        health_score=100.0,
        last_heartbeat=datetime.now(timezone.utc),
        capabilities=DeviceCapabilities(
            arch="x86_64", cpu_cores=8, ram_total_mb=16384,
        ),
    )


def test_dispatch_records_audit_entry(audit_tmpdir):
    """Dispatch exitoso escribe entry con category='dispatch'."""
    registry = MeshRegistry()
    d = _make_device("d1")
    registry.save_device(d)

    svc = DispatchService(registry)
    fp = TaskFingerprint(action_class="code_gen", requires_context_kb=0)
    decision = svc.dispatch(fp, mesh_enabled=True, task_id="t-123")

    assert decision.device_id == "d1"

    audit_log = audit_tmpdir / "mesh" / "audit.jsonl"
    assert audit_log.exists(), "audit.jsonl no creado"
    entries = [json.loads(line) for line in audit_log.read_text().splitlines() if line.strip()]
    dispatch_entries = [e for e in entries if e["category"] == "dispatch"]
    assert len(dispatch_entries) == 1, f"esperaba 1 entry dispatch, hay {len(dispatch_entries)}"

    entry = dispatch_entries[0]
    assert entry["action"] == "routed"
    assert entry["device_id"] == "d1"
    assert entry["task_id"] == "t-123"
    assert entry["details"]["action_class"] == "code_gen"
    assert entry["details"]["fallback_to_local"] is False


def test_dispatch_records_fallback_to_local(audit_tmpdir):
    """Cuando mesh_enabled=False, audit action='fallback_to_local'."""
    registry = MeshRegistry()
    svc = DispatchService(registry)
    fp = TaskFingerprint(action_class="code_gen", requires_context_kb=0)
    svc.dispatch(fp, mesh_enabled=False, task_id="t-off")

    audit_log = audit_tmpdir / "mesh" / "audit.jsonl"
    entries = [json.loads(line) for line in audit_log.read_text().splitlines() if line.strip()]
    dispatch_entries = [e for e in entries if e["category"] == "dispatch"]
    assert len(dispatch_entries) == 1
    assert dispatch_entries[0]["action"] == "fallback_to_local"
    assert dispatch_entries[0]["details"]["fallback_to_local"] is True


def test_dispatch_audit_includes_fit_level(audit_tmpdir):
    """Cuando dispatch usa preferred_model_meta, fit_level queda en detalles."""
    registry = MeshRegistry()
    d = _make_device("d1")
    registry.save_device(d)

    svc = DispatchService(registry)
    fp = TaskFingerprint(action_class="code_gen", requires_context_kb=0)
    svc.dispatch(
        fp,
        mesh_enabled=True,
        task_id="t-fit",
        preferred_model_meta={
            "model_id": "tiny",
            "params_str": "1b",
            "quant_str": "q4_k_m",
            "size_bytes": 700_000_000,
        },
    )

    audit_log = audit_tmpdir / "mesh" / "audit.jsonl"
    entries = [json.loads(line) for line in audit_log.read_text().splitlines() if line.strip()]
    dispatch_entries = [e for e in entries if e["category"] == "dispatch"]
    assert len(dispatch_entries) == 1
    # fit_level debe estar populado (optimal/comfortable/tight/overload) pero
    # depende de lo que compute ModelRecommendationEngine; basta con verify
    # que el field EXISTE en los details
    assert "model_fit_level" in dispatch_entries[0]["details"]


def test_dispatch_audit_survives_without_task_id(audit_tmpdir):
    """Si no se pasa task_id, el audit igual escribe (task_id='')."""
    registry = MeshRegistry()
    d = _make_device("d1")
    registry.save_device(d)

    svc = DispatchService(registry)
    fp = TaskFingerprint(action_class="code_gen", requires_context_kb=0)
    decision = svc.dispatch(fp, mesh_enabled=True)

    assert decision.device_id == "d1"

    audit_log = audit_tmpdir / "mesh" / "audit.jsonl"
    entries = [json.loads(line) for line in audit_log.read_text().splitlines() if line.strip()]
    dispatch_entries = [e for e in entries if e["category"] == "dispatch"]
    assert len(dispatch_entries) == 1
    assert dispatch_entries[0]["task_id"] == ""


def test_dispatch_audit_failure_does_not_break_dispatch(audit_tmpdir, monkeypatch):
    """Si MeshAuditService.record() raise, el dispatch sigue devolviendo decision."""
    registry = MeshRegistry()
    d = _make_device("d1")
    registry.save_device(d)

    svc = DispatchService(registry)

    class _BrokenAudit:
        def record(self, **kw):
            raise RuntimeError("disk full")

    import tools.gimo_server.services.mesh.audit as audit_mod
    monkeypatch.setattr(audit_mod, "MeshAuditService", lambda: _BrokenAudit())

    fp = TaskFingerprint(action_class="code_gen", requires_context_kb=0)
    decision = svc.dispatch(fp, mesh_enabled=True, task_id="t-crash")

    # El dispatch sigue funcionando a pesar de que el audit revente
    assert decision.device_id == "d1"
