"""
OPS v2 Multi-Agent Trigger — Tests E2E
Covers: roles, workflow, auto_run, security constraints.
"""

import os
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ORCH_REPO_ROOT", str(Path(__file__).parent.parent.resolve()))

from tools.gimo_server.config import (
    ORCH_ACTIONS_TOKEN,
    ORCH_OPERATOR_TOKEN,
    TOKENS,
)
from tools.gimo_server.main import app
from tools.gimo_server.security import load_security_db, save_security_db
from tools.gimo_server.services.ops_service import OpsService


def _admin_headers() -> dict[str, str]:
    token = os.environ.get("ORCH_TOKEN", "")
    if not token:
        # fallback: pick the admin token from TOKENS
        token = next(t for t in TOKENS if t != ORCH_ACTIONS_TOKEN and t != ORCH_OPERATOR_TOKEN)
    return {"Authorization": f"Bearer {token}"}


def _operator_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ORCH_OPERATOR_TOKEN}"}


def _actions_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ORCH_ACTIONS_TOKEN}"}


@pytest.fixture(autouse=True)
def clean_ops_state():
    """Reset OPS state before each test."""
    db = load_security_db()
    db["panic_mode"] = False
    db["recent_events"] = []
    save_security_db(db)
    app.dependency_overrides.clear()
    app.state.start_time = time.time()

    # Clean OPS storage
    for subdir in ("drafts", "approved", "runs"):
        d = OpsService.OPS_DIR / subdir
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    for f in ("plan.json", "config.json"):
        p = OpsService.OPS_DIR / f
        if p.exists():
            p.unlink()
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ═══════════════════════════════════════════
# Role Tests
# ═══════════════════════════════════════════


class TestRoles:
    def test_three_tokens_exist(self):
        assert len(TOKENS) == 3

    def test_actions_can_read_plan(self, client: TestClient):
        r = client.get("/ops/plan", headers=_actions_headers())
        assert r.status_code in (200, 404)  # 404 = plan not set, still accessible

    def test_actions_can_list_drafts(self, client: TestClient):
        r = client.get("/ops/drafts", headers=_actions_headers())
        assert r.status_code == 200

    def test_actions_cannot_create_draft(self, client: TestClient):
        r = client.post(
            "/ops/drafts",
            headers={**_actions_headers(), "Content-Type": "application/json"},
            json={"prompt": "test"},
        )
        assert r.status_code == 403

    def test_actions_cannot_approve(self, client: TestClient):
        # Create a draft as admin first
        rd = client.post(
            "/ops/drafts",
            headers={**_admin_headers(), "Content-Type": "application/json"},
            json={"prompt": "test"},
        )
        draft_id = rd.json()["id"]
        r = client.post(f"/ops/drafts/{draft_id}/approve", headers=_actions_headers())
        assert r.status_code == 403

    def test_actions_cannot_create_run(self, client: TestClient):
        r = client.post(
            "/ops/runs",
            headers={**_actions_headers(), "Content-Type": "application/json"},
            json={"approved_id": "a_fake"},
        )
        assert r.status_code == 403

    def test_actions_cannot_access_provider(self, client: TestClient):
        r = client.get("/ops/provider", headers=_actions_headers())
        assert r.status_code == 403

    def test_operator_can_approve(self, client: TestClient):
        rd = client.post(
            "/ops/drafts",
            headers={**_admin_headers(), "Content-Type": "application/json"},
            json={"prompt": "operator approval test"},
        )
        assert rd.status_code == 201
        draft_id = rd.json()["id"]
        # Set content so approve works
        client.put(
            f"/ops/drafts/{draft_id}",
            headers={**_admin_headers(), "Content-Type": "application/json"},
            json={"content": "some content"},
        )
        r = client.post(f"/ops/drafts/{draft_id}/approve", headers=_operator_headers())
        assert r.status_code == 200

    def test_operator_can_create_run(self, client: TestClient):
        rd = client.post(
            "/ops/drafts",
            headers={**_admin_headers(), "Content-Type": "application/json"},
            json={"prompt": "run test"},
        )
        draft_id = rd.json()["id"]
        client.put(
            f"/ops/drafts/{draft_id}",
            headers={**_admin_headers(), "Content-Type": "application/json"},
            json={"content": "run content"},
        )
        ra = client.post(f"/ops/drafts/{draft_id}/approve", headers=_operator_headers())
        approved_id = ra.json()["approved"]["id"]
        rr = client.post(
            "/ops/runs",
            headers={**_operator_headers(), "Content-Type": "application/json"},
            json={"approved_id": approved_id},
        )
        assert rr.status_code == 201

    def test_operator_cannot_set_plan(self, client: TestClient):
        r = client.put(
            "/ops/plan",
            headers={**_operator_headers(), "Content-Type": "application/json"},
            json={"id": "p1", "title": "t", "workspace": "w", "created": "c", "objective": "o", "tasks": []},
        )
        assert r.status_code == 403

    def test_operator_cannot_set_provider(self, client: TestClient):
        r = client.put(
            "/ops/provider",
            headers={**_operator_headers(), "Content-Type": "application/json"},
            json={"active": "x", "providers": {}},
        )
        assert r.status_code == 403

    def test_operator_cannot_set_config(self, client: TestClient):
        r = client.put(
            "/ops/config",
            headers={**_operator_headers(), "Content-Type": "application/json"},
            json={"default_auto_run": True, "draft_cleanup_ttl_days": 7, "max_concurrent_runs": 3, "operator_can_generate": False},
        )
        assert r.status_code == 403

    def test_operator_can_read_config(self, client: TestClient):
        r = client.get("/ops/config", headers=_operator_headers())
        assert r.status_code == 200


# ═══════════════════════════════════════════
# Workflow Tests
# ═══════════════════════════════════════════


class TestWorkflow:
    def test_full_workflow(self, client: TestClient):
        """draft → approve → run (manual)"""
        h = {**_admin_headers(), "Content-Type": "application/json"}

        # Create draft
        r1 = client.post("/ops/drafts", headers=h, json={"prompt": "implement feature X"})
        assert r1.status_code == 201
        draft = r1.json()
        assert draft["status"] == "draft"
        draft_id = draft["id"]

        # Set content
        client.put(f"/ops/drafts/{draft_id}", headers=h, json={"content": "code here"})

        # Approve
        r2 = client.post(f"/ops/drafts/{draft_id}/approve", headers=_admin_headers())
        assert r2.status_code == 200
        data = r2.json()
        assert data["approved"]["draft_id"] == draft_id
        assert data["run"] is None  # default_auto_run is False
        approved_id = data["approved"]["id"]

        # Check draft status updated
        r3 = client.get(f"/ops/drafts/{draft_id}", headers=_admin_headers())
        assert r3.json()["status"] == "approved"

        # Create run
        r4 = client.post("/ops/runs", headers=h, json={"approved_id": approved_id})
        assert r4.status_code == 201
        assert r4.json()["status"] == "pending"

    def test_reject_workflow(self, client: TestClient):
        h = {**_admin_headers(), "Content-Type": "application/json"}
        r1 = client.post("/ops/drafts", headers=h, json={"prompt": "bad idea"})
        draft_id = r1.json()["id"]

        r2 = client.post(f"/ops/drafts/{draft_id}/reject", headers=_admin_headers())
        assert r2.status_code == 200
        assert r2.json()["status"] == "rejected"

        # Cannot approve rejected
        r3 = client.post(f"/ops/drafts/{draft_id}/approve", headers=_admin_headers())
        assert r3.status_code == 404  # ValueError → 404

    def test_cannot_run_from_draft_id(self, client: TestClient):
        h = {**_admin_headers(), "Content-Type": "application/json"}
        r1 = client.post("/ops/drafts", headers=h, json={"prompt": "test"})
        draft_id = r1.json()["id"]

        r2 = client.post("/ops/runs", headers=h, json={"approved_id": draft_id})
        assert r2.status_code == 403
        assert "approved_id" in r2.json()["detail"].lower() or "only" in r2.json()["detail"].lower()


# ═══════════════════════════════════════════
# Auto-Run Tests
# ═══════════════════════════════════════════


class TestAutoRun:
    def _create_and_set_content(self, client: TestClient, prompt: str = "auto test") -> str:
        h = {**_admin_headers(), "Content-Type": "application/json"}
        r = client.post("/ops/drafts", headers=h, json={"prompt": prompt})
        draft_id = r.json()["id"]
        client.put(f"/ops/drafts/{draft_id}", headers=h, json={"content": "auto content"})
        return draft_id

    def test_auto_run_true(self, client: TestClient):
        draft_id = self._create_and_set_content(client)
        r = client.post(
            f"/ops/drafts/{draft_id}/approve?auto_run=true",
            headers=_admin_headers(),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["approved"] is not None
        assert data["run"] is not None
        assert data["run"]["status"] == "pending"

    def test_auto_run_false(self, client: TestClient):
        draft_id = self._create_and_set_content(client)
        r = client.post(
            f"/ops/drafts/{draft_id}/approve?auto_run=false",
            headers=_admin_headers(),
        )
        data = r.json()
        assert data["run"] is None

    def test_auto_run_default_from_config(self, client: TestClient):
        h = {**_admin_headers(), "Content-Type": "application/json"}
        # Set default_auto_run to True
        client.put("/ops/config", headers=h, json={
            "default_auto_run": True,
            "draft_cleanup_ttl_days": 7,
            "max_concurrent_runs": 3,
            "operator_can_generate": False,
        })
        draft_id = self._create_and_set_content(client)
        r = client.post(f"/ops/drafts/{draft_id}/approve", headers=_admin_headers())
        data = r.json()
        assert data["run"] is not None  # auto_run from config default


# ═══════════════════════════════════════════
# Security Tests
# ═══════════════════════════════════════════


class TestSecurity:
    def test_no_token(self, client: TestClient):
        r = client.get("/ops/plan")
        assert r.status_code == 401

    def test_invalid_token(self, client: TestClient):
        r = client.get("/ops/plan", headers={"Authorization": "Bearer invalid-short"})
        assert r.status_code == 401

    def test_approved_by_does_not_contain_raw_token(self, client: TestClient):
        h = {**_admin_headers(), "Content-Type": "application/json"}
        r1 = client.post("/ops/drafts", headers=h, json={"prompt": "sec test"})
        draft_id = r1.json()["id"]
        client.put(f"/ops/drafts/{draft_id}", headers=h, json={"content": "content"})
        r2 = client.post(f"/ops/drafts/{draft_id}/approve", headers=_admin_headers())
        approved = r2.json()["approved"]
        # approved_by should be "admin:<hash>" not the raw token
        assert approved["approved_by"].startswith("admin:")
        admin_token = next(t for t in TOKENS if t != ORCH_ACTIONS_TOKEN and t != ORCH_OPERATOR_TOKEN)
        assert admin_token not in approved["approved_by"]

    def test_cancel_terminal_run_returns_409(self, client: TestClient):
        h = {**_admin_headers(), "Content-Type": "application/json"}
        r1 = client.post("/ops/drafts", headers=h, json={"prompt": "cancel test"})
        draft_id = r1.json()["id"]
        client.put(f"/ops/drafts/{draft_id}", headers=h, json={"content": "c"})
        r2 = client.post(f"/ops/drafts/{draft_id}/approve?auto_run=true", headers=_admin_headers())
        run_id = r2.json()["run"]["id"]

        # Cancel once
        rc = client.post(f"/ops/runs/{run_id}/cancel", headers=_admin_headers())
        assert rc.status_code == 200
        assert rc.json()["status"] == "cancelled"

        # Cancel again → 409
        rc2 = client.post(f"/ops/runs/{run_id}/cancel", headers=_admin_headers())
        assert rc2.status_code == 409


# ═══════════════════════════════════════════
# Config Tests
# ═══════════════════════════════════════════


class TestConfig:
    def test_default_config(self, client: TestClient):
        r = client.get("/ops/config", headers=_admin_headers())
        assert r.status_code == 200
        cfg = r.json()
        assert cfg["default_auto_run"] is False
        assert cfg["max_concurrent_runs"] == 3

    def test_admin_can_update_config(self, client: TestClient):
        h = {**_admin_headers(), "Content-Type": "application/json"}
        r = client.put("/ops/config", headers=h, json={
            "default_auto_run": True,
            "draft_cleanup_ttl_days": 14,
            "max_concurrent_runs": 5,
            "operator_can_generate": True,
        })
        assert r.status_code == 200
        assert r.json()["default_auto_run"] is True
        assert r.json()["max_concurrent_runs"] == 5

    def test_config_persists(self, client: TestClient):
        h = {**_admin_headers(), "Content-Type": "application/json"}
        client.put("/ops/config", headers=h, json={
            "default_auto_run": True,
            "draft_cleanup_ttl_days": 30,
            "max_concurrent_runs": 2,
            "operator_can_generate": False,
        })
        r = client.get("/ops/config", headers=_admin_headers())
        assert r.json()["draft_cleanup_ttl_days"] == 30
