from __future__ import annotations

from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext


def _override_auth() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


import asyncio

def test_codex_login_legacy_endpoint_returns_actionable_error(monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth

    from tools.gimo_server.services.codex_auth_service import CodexAuthService

    async def _fake_flow():
        await asyncio.sleep(0)
        return {
            "status": "error",
            "message": "Codex CLI no detectado",
            "action": "npm install -g @openai/codex",
        }

    monkeypatch.setattr(CodexAuthService, "start_device_flow", _fake_flow)

    try:
        client = TestClient(app)
        res = client.post("/ops/provider/codex/device-login")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "error"
        assert body["message"] == "Codex CLI no detectado"
        assert body["action"] == "npm install -g @openai/codex"
    finally:
        app.dependency_overrides.clear()


def test_codex_login_connectors_endpoint_keeps_current_contract(monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth

    from tools.gimo_server.services.codex_auth_service import CodexAuthService

    async def _fake_flow():
        await asyncio.sleep(0)
        return {
            "status": "pending",
            "verification_url": "https://openai.com/device",
            "user_code": "ABCD-1234",
            "poll_id": "poll-1",
        }

    monkeypatch.setattr(CodexAuthService, "start_device_flow", _fake_flow)

    try:
        client = TestClient(app)
        res = client.post("/ops/connectors/codex/login")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "pending"
        assert body["user_code"] == "ABCD-1234"
        assert body["poll_id"] == "poll-1"
    finally:
        app.dependency_overrides.clear()


def test_generic_provider_auth_status_dispatches(monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth

    from tools.gimo_server.services.codex_auth_service import CodexAuthService

    async def _fake_status():
        await asyncio.sleep(0)
        return {"authenticated": True, "provider": "codex"}

    monkeypatch.setattr(CodexAuthService, "get_auth_status", _fake_status)

    try:
        client = TestClient(app)
        res = client.get("/ops/connectors/codex/auth-status")
        assert res.status_code == 200
        assert res.json()["authenticated"] is True
    finally:
        app.dependency_overrides.clear()


def test_generic_provider_logout_dispatches(monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth

    from tools.gimo_server.services.claude_auth_service import ClaudeAuthService

    async def _fake_logout():
        await asyncio.sleep(0)
        return {"status": "logged_out", "provider": "claude"}

    monkeypatch.setattr(ClaudeAuthService, "logout", _fake_logout)

    try:
        client = TestClient(app)
        res = client.post("/ops/connectors/claude/logout")
        assert res.status_code == 200
        assert res.json()["status"] == "logged_out"
    finally:
        app.dependency_overrides.clear()
