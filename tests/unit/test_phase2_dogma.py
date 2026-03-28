from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tools.gimo_server.main import app
from tools.gimo_server.ops_models import ActionDraft, ExecutorReport
from tools.gimo_server.routers.ops import run_router
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.hitl_gate_service import HitlGateService
from tools.gimo_server.services.role_profiles import assert_tool_allowed, get_role_profile
from tools.gimo_server.services.critic_service import CriticService


def _override_auth() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


@pytest.fixture(autouse=True)
def _reset_hitl_state():
    HitlGateService._waiters.clear()  # type: ignore[attr-defined]
    yield
    HitlGateService._waiters.clear()  # type: ignore[attr-defined]


def test_executor_report_requires_rollback_plan():
    with pytest.raises(ValidationError):
        ExecutorReport(
            run_id="r1",
            agent_id="executor",
            modified_files=["a.py"],
            safety_summary="ok",
            rollback_plan=[],
            timestamp="2026-01-01T00:00:00Z",
        )


@pytest.mark.asyncio
async def test_hitl_timeout_rejects(monkeypatch):
    async def _noop_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr("tools.gimo_server.services.hitl_gate_service.NotificationService.publish", _noop_publish)

    decision = await HitlGateService.gate_tool_call(
        agent_id="agent:test",
        tool="run_command",
        params={"cmd": "echo hi"},
        timeout_seconds=0.05,
    )
    assert decision == "reject"

    drafts = HitlGateService.list_drafts(status="timeout")
    assert drafts
    assert drafts[0].status == "timeout"


@pytest.mark.asyncio
async def test_hitl_approve_resumes(monkeypatch):
    async def _noop_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr("tools.gimo_server.services.hitl_gate_service.NotificationService.publish", _noop_publish)

    async def _runner():
        return await HitlGateService.gate_tool_call(
            agent_id="agent:test",
            tool="run_command",
            params={"cmd": "echo hi"},
            timeout_seconds=1.0,
        )

    task = asyncio.create_task(_runner())
    await asyncio.sleep(0.05)
    pending = HitlGateService.list_drafts(status="pending")
    assert pending

    await HitlGateService.approve(pending[0].id)
    decision = await task
    assert decision == "allow"


def test_role_enforcement_explorer_denies_write_tool():
    with pytest.raises(PermissionError):
        assert_tool_allowed("explorer", "write_to_file")


def test_role_profiles_reflect_canonical_policy_catalog():
    explorer = get_role_profile("explorer")
    auditor = get_role_profile("auditor")
    executor = get_role_profile("executor")

    assert explorer.capability == "docs_research"
    assert explorer.trust_tier == "t1"
    assert auditor.capability == "security_audit"
    assert auditor.hitl_required is True
    assert executor.capability == "workspace_safe"
    assert executor.trust_tier == "t2"


def test_action_drafts_endpoints(monkeypatch):
    local_app = FastAPI()
    local_app.include_router(run_router.router, prefix="/ops")
    local_app.dependency_overrides[verify_token] = _override_auth

    draft = ActionDraft(agent_id="a1", tool="run_command", params={"cmd": "x"})

    monkeypatch.setattr(run_router.HitlGateService, "list_drafts", lambda status=None: [draft])

    async def _approve(_draft_id: str, reason=None):
        return draft

    async def _reject(_draft_id: str, reason=None):
        return draft

    monkeypatch.setattr(run_router.HitlGateService, "approve", _approve)
    monkeypatch.setattr(run_router.HitlGateService, "reject", _reject)

    try:
        with TestClient(local_app) as client:
            res = client.get("/ops/action-drafts")
            assert res.status_code == 200
            assert isinstance(res.json(), list)

            res_ap = client.post(f"/ops/action-drafts/{draft.id}/approve")
            assert res_ap.status_code == 200
            assert res_ap.json()["id"] == draft.id

            res_rj = client.post(f"/ops/action-drafts/{draft.id}/reject")
            assert res_rj.status_code == 200
            assert res_rj.json()["id"] == draft.id
    finally:
        local_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_critic_fail_closed_on_invalid_payload(monkeypatch):
    async def _fake_generate(*_args, **_kwargs):
        return {"content": "not json"}

    monkeypatch.setattr("tools.gimo_server.services.critic_service.ProviderService.static_generate", _fake_generate)
    verdict = await CriticService.evaluate("output")
    assert verdict.approved is False
    assert verdict.severity == "major"
