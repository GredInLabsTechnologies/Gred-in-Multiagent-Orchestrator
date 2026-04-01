"""Phase 1 consolidated tests.

Merged from:
- test_phase1_hardening.py (8 tests)
- test_phase1_skills.py (3 tests)
- test_phase1_mcp_aliases.py (1 test)
- test_phase1_frontend_backend_contract.py (1 test)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.authority import ExecutionAuthority
from tools.gimo_server.services.log_rotation_service import LogRotationService
from tools.gimo_server.services.notification_service import (
    NotificationService,
    CIRCUIT_BREAKER_THRESHOLD,
)
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.resource_governor import (
    AdmissionDecision,
    ResourceGovernor,
    TaskWeight,
)
from tools.gimo_server.routers.ops import observability_router
from tools.gimo_server.services import skills_service


def _override_auth() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


# ── Hardening fixtures ──────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_hardening_state(monkeypatch, tmp_path):
    NotificationService.reset_state_for_tests()
    ExecutionAuthority.reset()
    monkeypatch.setattr(OpsService, "OPS_DIR", tmp_path)
    monkeypatch.setattr(OpsService, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(OpsService, "APPROVED_DIR", tmp_path / "approved")
    monkeypatch.setattr(OpsService, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(OpsService, "RUN_EVENTS_DIR", tmp_path / "run_events")
    monkeypatch.setattr(OpsService, "RUN_LOGS_DIR", tmp_path / "run_logs")
    monkeypatch.setattr(OpsService, "LOCKS_DIR", tmp_path / "locks")
    monkeypatch.setattr(OpsService, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(OpsService, "LOCK_FILE", tmp_path / ".ops.lock")
    OpsService.ensure_dirs()
    app.dependency_overrides[verify_token] = _override_auth
    yield
    app.dependency_overrides.clear()
    NotificationService.reset_state_for_tests()
    ExecutionAuthority.reset()


# ── Hardening tests (from test_phase1_hardening.py) ─────────


def test_realtime_metrics_endpoint_exposes_notification_metrics():
    local_app = FastAPI()
    local_app.include_router(observability_router.router, prefix="/ops")
    local_app.dependency_overrides[verify_token] = _override_auth
    with TestClient(local_app) as client:
        resp = client.get("/ops/realtime/metrics")
        assert resp.status_code == 200
        payload = resp.json()
        assert "published" in payload
        assert "dropped" in payload


def test_circuit_breaker_opens_for_slow_subscriber(monkeypatch):
    NotificationService.configure(queue_maxsize=1)
    _ = asyncio.run(NotificationService.subscribe())

    async def _emit_many():
        for idx in range(CIRCUIT_BREAKER_THRESHOLD + 2):
            await NotificationService._broadcast_now("evt", {"idx": idx, "critical": True})

    asyncio.run(_emit_many())
    metrics = NotificationService.get_metrics()
    assert metrics["circuit_opens"] >= 1


def test_event_driven_worker_notify_sets_wake_event():
    from tools.gimo_server.services.run_worker import RunWorker

    worker = RunWorker()
    assert not worker._wake_event.is_set()
    worker.notify()
    assert worker._wake_event.is_set()


def test_resource_governor_defers_on_high_cpu_and_vram():
    @dataclass
    class _Snap:
        cpu_percent: float
        ram_percent: float
        gpu_vram_free_gb: float
        gpu_vram_gb: float
        gpu_temp: float

    class _Hw:
        def __init__(self, snap):
            self._snap = snap

        def get_snapshot(self):
            return self._snap

    gov_cpu = ResourceGovernor(_Hw(_Snap(95.0, 40.0, 4.0, 8.0, 40.0)))
    assert gov_cpu.evaluate(TaskWeight.MEDIUM) == AdmissionDecision.DEFER

    gov_vram = ResourceGovernor(_Hw(_Snap(20.0, 30.0, 0.2, 8.0, 40.0)))
    assert gov_vram.evaluate(TaskWeight.HEAVY) == AdmissionDecision.DEFER


def test_append_only_state_and_materialized_read():
    approved = OpsService.create_draft(prompt="p", content="c")
    appr = OpsService.approve_draft(approved.id, approved_by="t")
    run = OpsService.create_run(appr.id)

    OpsService.update_run_status(run.id, "running", msg="start")
    OpsService.set_run_stage(run.id, "stage-1")
    OpsService.update_run_status(run.id, "done", msg="end")

    run_json = OpsService._run_path(run.id)
    events_jsonl = OpsService._run_events_path(run.id)
    assert run_json.exists()
    assert events_jsonl.exists()
    lines = [ln for ln in events_jsonl.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 3

    materialized = OpsService.get_run(run.id)
    assert materialized is not None
    assert materialized.status == "done"
    assert materialized.stage == "stage-1"


def test_sub_agent_reconcile_ignores_worktree_dirs_and_prunes_missing_workspaces(tmp_path, monkeypatch):
    """Startup reconcile is keyed to provisioned workspace paths, not worktree directories."""
    from tools.gimo_server.services.sub_agent_manager import SubAgentManager

    worktrees_dir = tmp_path / "worktrees"
    worktrees_dir.mkdir()

    orphan = worktrees_dir / "orphan_abc"
    orphan.mkdir()
    (orphan / "dummy.txt").write_text("x")

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    inv_file = runtime_dir / "sub_agents.json"
    kept_workspace = tmp_path / "ephemeral" / "kept_xyz"
    kept_workspace.mkdir(parents=True, exist_ok=True)
    inv_file.write_text(json.dumps({
        "kept_xyz": {
            "id": "kept_xyz", "parentId": "system", "name": "Kept",
            "model": "test", "status": "idle", "worktreePath": str(kept_workspace),
            "config": {"model": "test", "temperature": 0.7, "max_tokens": 2048},
        },
        "ghost_xyz": {
            "id": "ghost_xyz", "parentId": "system", "name": "Ghost",
            "model": "test", "status": "idle", "worktreePath": str(tmp_path / "ephemeral" / "ghost_xyz"),
            "config": {"model": "test", "temperature": 0.7, "max_tokens": 2048},
        }
    }))

    monkeypatch.setattr("tools.gimo_server.services.sub_agent_manager.INVENTORY_FILE", inv_file)

    async def _noop_sync():
        pass

    monkeypatch.setattr(SubAgentManager, "sync_with_ollama", classmethod(lambda cls: _noop_sync()))
    SubAgentManager._sub_agents = {}

    asyncio.run(SubAgentManager.startup_reconcile())

    assert orphan.exists()
    assert "kept_xyz" in SubAgentManager._sub_agents
    assert "ghost_xyz" not in SubAgentManager._sub_agents


def test_gics_retry_with_backoff(monkeypatch):
    """GICS retry delivers after transient failures."""
    from tools.gimo_server.services.gics_service import GicsService

    svc = GicsService()
    svc._token = "test-token"
    call_count = {"n": 0}

    def _fake_send(method, params=None):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise ConnectionError("fake transient")
        return {"result": "ok"}

    monkeypatch.setattr(svc, "send_command", _fake_send)
    monkeypatch.setattr("time.sleep", lambda _: None)

    result = svc._send_with_retry("put", {"key": "k", "fields": {}})
    assert result == {"result": "ok"}
    assert call_count["n"] == 3


def test_log_rotation_rotates_and_deletes(tmp_path, monkeypatch):
    scan_dir = tmp_path / "logs"
    scan_dir.mkdir(parents=True, exist_ok=True)
    old_file = scan_dir / "old.log"
    old_file.write_text("x", encoding="utf-8")
    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
    os.utime(old_file, (old_ts, old_ts))

    large_file = scan_dir / "large.log"
    large_file.write_bytes(b"a" * (50 * 1024 * 1024 + 32))

    monkeypatch.setattr("tools.gimo_server.services.observability_pkg.log_rotation_service.SCAN_DIRS", [scan_dir])
    monkeypatch.setattr("tools.gimo_server.services.observability_pkg.log_rotation_service.OPS_DATA_DIR", tmp_path)

    stats = LogRotationService.run_rotation()
    assert stats["deleted"] >= 1
    assert stats["compressed"] >= 1
    assert (scan_dir / "large.log.gz").exists()


# ── Skills tests (from test_phase1_skills.py) ───────────────


def _valid_skill_payload(command: str = "/explorar") -> dict:
    return {
        "name": "Exploración de repo",
        "description": "Recorre módulos principales",
        "command": command,
        "replace_graph": False,
        "nodes": [
            {"id": "orch", "type": "orchestrator"},
            {"id": "worker_1", "type": "worker"},
        ],
        "edges": [
            {"source": "orch", "target": "worker_1"},
        ],
    }


def test_phase1_skills_crud_and_validations(tmp_path, monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth
    monkeypatch.setattr(skills_service, "SKILLS_DIR", tmp_path / "skills")

    try:
        client = TestClient(app)
        create_res = client.post("/ops/skills", json=_valid_skill_payload())
        assert create_res.status_code == 201
        created = create_res.json()
        assert created["command"] == "/explorar"

        dup_res = client.post("/ops/skills", json=_valid_skill_payload("/explorar"))
        assert dup_res.status_code == 409

        cycle_payload = _valid_skill_payload("/ciclo")
        cycle_payload["edges"] = [
            {"source": "orch", "target": "worker_1"},
            {"source": "worker_1", "target": "orch"},
        ]
        cycle_res = client.post("/ops/skills", json=cycle_payload)
        assert cycle_res.status_code == 400

        list_res = client.get("/ops/skills")
        assert list_res.status_code == 200
        listed = list_res.json()
        assert isinstance(listed, list)
        assert len(listed) == 1
        assert listed[0]["command"] == "/explorar"

        delete_res = client.delete(f"/ops/skills/{created['id']}")
        assert delete_res.status_code == 204

        list_after_delete = client.get("/ops/skills")
        assert list_after_delete.status_code == 200
        assert list_after_delete.json() == []
    finally:
        app.dependency_overrides.clear()


def test_phase1_skills_generate_description(tmp_path, monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth
    monkeypatch.setattr(skills_service, "SKILLS_DIR", tmp_path / "skills")

    try:
        client = TestClient(app)
        res = client.post(
            "/ops/skills/generate-description",
            json={
                "name": "Análisis",
                "command": "/analizar",
                "nodes": [{"id": "orch", "type": "orchestrator"}],
                "edges": [],
            },
        )
        assert res.status_code == 200
        assert "description" in res.json()
        assert "/analizar" in res.json()["description"]
    finally:
        app.dependency_overrides.clear()


def test_phase1_skills_execute_returns_run_id(tmp_path, monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth
    monkeypatch.setattr(skills_service, "SKILLS_DIR", tmp_path / "skills")

    async def _fake_execute_skill(skill_id: str, req):
        await asyncio.sleep(0)
        return skills_service.SkillExecuteResponse(
            skill_run_id="skill_run_test_1234",
            skill_id=skill_id,
            replace_graph=req.replace_graph,
            status="queued",
        )

    monkeypatch.setattr(skills_service.SkillsService, "execute_skill", _fake_execute_skill)

    try:
        client = TestClient(app)
        create_res = client.post("/ops/skills", json=_valid_skill_payload("/ejecutar"))
        assert create_res.status_code == 201
        created = create_res.json()

        exec_res = client.post(
            f"/ops/skills/{created['id']}/execute",
            json={"replace_graph": False, "context": {}},
        )
        assert exec_res.status_code == 201
        body = exec_res.json()
        assert body["skill_run_id"] == "skill_run_test_1234"
        assert body["skill_id"] == created["id"]
        assert body["status"] == "queued"
    finally:
        app.dependency_overrides.clear()


# ── MCP aliases test (from test_phase1_mcp_aliases.py) ──────


def test_phase1_mcp_alias_tools_are_registered():
    from tools.gimo_server.mcp_bridge import registrar

    class _DummyMcp:
        def __init__(self) -> None:
            self.tools: list[str] = []

        def add_tool(self, func) -> None:
            self.tools.append(func.__name__)

    dummy = _DummyMcp()
    registrar.register_all(dummy)
    tool_names = set(dummy.tools)
    assert "plan_create" in tool_names
    assert "plan_execute" in tool_names
    assert "cost_estimate" in tool_names


# ── Frontend-backend contract (from test_phase1_frontend_backend_contract.py) ──


UI_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "tools" / "orchestrator_ui" / "src"
FETCH_PATTERN = re.compile(r"fetch\(\s*`\$\{API_BASE\}([^`]+)`")
IGNORED_DYNAMIC_PATHS = {
    "/ui/service/{param}",
}


def _normalize_frontend_path(raw: str) -> str:
    path = raw.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]+\}", "{param}", path)
    if path.endswith("{param}") and not path.endswith("/{param}"):
        path = path[: -len("{param}")]
    path = path.replace("{param}{param}", "{param}")
    return path.rstrip("/") or "/"


def _frontend_paths() -> set[str]:
    out: set[str] = set()
    for file_path in UI_SOURCE_ROOT.rglob("*.[tj]s*"):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        for match in FETCH_PATTERN.finditer(text):
            normalized = _normalize_frontend_path(match.group(1))
            if normalized == "{param}":
                continue
            out.add(normalized)
    return out


def _backend_paths() -> set[str]:
    out: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if not path:
            continue
        normalized = re.sub(r"\{[^}]+\}", "{param}", path).rstrip("/") or "/"
        out.add(normalized)
    return out


def test_phase1_frontend_api_paths_exist_in_backend():
    frontend_paths = _frontend_paths()
    backend_paths = _backend_paths()

    missing = sorted(
        path for path in frontend_paths
        if path not in backend_paths and path not in IGNORED_DYNAMIC_PATHS
    )

    assert missing == []
