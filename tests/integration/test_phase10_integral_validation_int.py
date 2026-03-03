from __future__ import annotations

import pytest

from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.repo_override_service import RepoOverrideService


pytestmark = pytest.mark.integration


def _override_admin() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


def test_phase10_integration_forbidden_path_rejected(test_client, monkeypatch):
    from tools.gimo_server.routers.ops import plan_router
    from tools.gimo_server.ops_models import PolicyDecision

    app.dependency_overrides[verify_token] = _override_admin
    monkeypatch.setattr(
        plan_router.RuntimePolicyService,
        "evaluate_draft_policy",
        lambda **_: PolicyDecision(
            policy_decision_id="pd10-int-1",
            decision="deny",
            status_code="DRAFT_REJECTED_FORBIDDEN_SCOPE",
            policy_hash_expected="h1",
            policy_hash_runtime="h1",
            triggered_rules=["forbidden_path:tools/gimo_server/security/auth.py"],
        ),
    )

    try:
        res = test_client.post(
            "/ops/drafts",
            json={
                "objective": "attempt forbidden",
                "constraints": ["none"],
                "acceptance_criteria": ["must reject"],
                "repo_context": {
                    "target_branch": "main",
                    "path_scope": ["tools/gimo_server/security/auth.py"],
                },
                "execution": {"intent_class": "SAFE_REFACTOR", "risk_score": 10},
            },
            headers={"Authorization": "Bearer test-token"},
        )
        assert res.status_code == 201
        payload = res.json()
        assert payload["status"] == "rejected"
        assert payload["error"] == "DRAFT_REJECTED_FORBIDDEN_SCOPE"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_phase10_integration_cloud_fallback_and_double_failure(monkeypatch):
    import httpx

    req = httpx.Request("POST", "http://localhost/v1/chat/completions")
    resp = httpx.Response(429, request=req)

    calls = {"n": 0}

    async def _primary_fails_then_local_ok(_prompt, _ctx):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise httpx.HTTPStatusError("too many requests", request=req, response=resp)
        return {"provider": "local_ollama", "model": "qwen3:8b", "content": "ok", "tokens_used": 1, "cost_usd": 0.0}

    monkeypatch.setattr(ProviderService, "static_generate", _primary_fails_then_local_ok)
    first = await ProviderService.static_generate_phase6_strategy(
        prompt="phase10",
        context={},
        intent_effective="SAFE_REFACTOR",
        path_scope=["tools/gimo_server/services/ops_service.py"],
    )
    assert first["fallback_used"] is True

    async def _all_fail(_prompt, _ctx):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(ProviderService, "static_generate", _all_fail)
    with pytest.raises(RuntimeError):
        await ProviderService.static_generate_phase6_strategy(
            prompt="phase10",
            context={},
            intent_effective="SAFE_REFACTOR",
            path_scope=["tools/gimo_server/services/ops_service.py"],
        )


@pytest.mark.asyncio
async def test_phase10_integration_account_mode_token_expired(monkeypatch):
    calls = {"n": 0}

    async def _auth_expired_then_local_ok(_prompt, _ctx):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("PROVIDER_AUTH_EXPIRED")
        return {"provider": "local_ollama", "model": "qwen3:8b", "content": "ok", "tokens_used": 1, "cost_usd": 0.0}

    monkeypatch.setattr(ProviderService, "static_generate", _auth_expired_then_local_ok)
    result = await ProviderService.static_generate_phase6_strategy(
        prompt="phase10-auth-expired-int",
        context={"auth_mode": "account"},
        intent_effective="SAFE_REFACTOR",
        path_scope=["tools/gimo_server/services/provider_service.py"],
    )
    assert result["fallback_used"] is True
    assert result["failure_reason"] == "provider_auth_expired"


def test_phase10_integration_restart_keeps_override(tmp_path, monkeypatch):
    override_path = tmp_path / "state" / "active_repo.json"
    monkeypatch.setattr(RepoOverrideService, "OVERRIDE_PATH", override_path)

    created = RepoOverrideService.set_human_override(repo_id=str(tmp_path / "repoA"), set_by_user="operator")
    after_restart = RepoOverrideService.get_active_override()

    assert after_restart is not None
    assert after_restart["repo_id"].endswith("repoA")
    assert after_restart["etag"] == created["etag"]
