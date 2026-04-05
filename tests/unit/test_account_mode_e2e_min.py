from __future__ import annotations

import asyncio
import shutil
from types import SimpleNamespace

from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.ops_models import ProviderConfig, ProviderEntry
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.providers.cli_account import CliAccountAdapter
from tools.gimo_server.services.provider_catalog_service import ProviderCatalogService
from tools.gimo_server.ops_models import ProviderValidateRequest, ProviderValidateResponse
from tools.gimo_server.ops_models import NormalizedModelInfo


def _override_auth() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


def test_provider_service_build_adapter_uses_cli_account_for_codex_account_mode():
    cfg = ProviderConfig(
        active="codex-main",
        providers={
            "codex-main": ProviderEntry(
                type="codex",
                provider_type="codex",
                auth_mode="account",
                model="gpt-5-codex",
            )
        },
    )

    adapter = ProviderService._build_adapter(cfg)

    assert isinstance(adapter, CliAccountAdapter)
    assert adapter.binary == "codex"


def test_account_login_start_routes_to_claude_flow(monkeypatch):
    app.dependency_overrides[verify_token] = _override_auth

    cfg = ProviderConfig(
        active="claude-main",
        providers={
            "claude-main": ProviderEntry(
                type="claude",
                provider_type="claude",
                auth_mode="account",
                model="claude-3-7-sonnet-latest",
            )
        },
    )

    from tools.gimo_server.services.claude_auth_service import ClaudeAuthService
    from tools.gimo_server.services.codex_auth_service import CodexAuthService
    from tools.gimo_server.services.provider_account_service import ProviderAccountService

    async def _fake_claude_login():
        return {
            "status": "pending",
            "verification_url": "https://claude.ai/device",
            "user_code": "ABCD-1234",
            "poll_id": "poll-claude",
        }

    async def _fake_codex_login():
        raise AssertionError("codex flow should not be used for claude provider")

    def _fake_start_flow(*, provider_id, verification_url, user_code, poll_id):
        return {
            "flow_id": "flow-1",
            "provider_id": provider_id,
            "verification_url": verification_url,
            "user_code": user_code,
            "poll_id": poll_id,
        }

    monkeypatch.setattr(ProviderService, "get_config", lambda: cfg)
    monkeypatch.setattr(ClaudeAuthService, "start_login_flow", _fake_claude_login)
    monkeypatch.setattr(CodexAuthService, "start_device_flow", _fake_codex_login)
    monkeypatch.setattr(ProviderAccountService, "start_flow", _fake_start_flow)

    try:
        client = TestClient(app)
        res = client.post("/ops/connectors/account/login/start", json={"provider_id": "claude-main"})
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "PROVIDER_AUTH_PENDING"
        assert body["provider_id"] == "claude-main"
        assert body["poll_id"] == "poll-claude"
    finally:
        app.dependency_overrides.clear()


def test_static_generate_uses_cli_account_adapter_for_codex(monkeypatch):
    cfg = ProviderConfig(
        active="codex-main",
        providers={
            "codex-main": ProviderEntry(
                type="codex",
                provider_type="codex",
                auth_mode="account",
                model="gpt-5-codex",
            )
        },
    )

    async def _fake_generate(self, prompt, context):
        return {
            "content": f"CLI_OK:{prompt}",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    monkeypatch.setattr(ProviderService, "get_config", lambda: cfg)
    monkeypatch.setattr(CliAccountAdapter, "generate", _fake_generate)

    from tools.gimo_server.services.ops_service import OpsService
    monkeypatch.setattr(
        OpsService,
        "get_config",
        lambda: SimpleNamespace(economy=SimpleNamespace(cache_enabled=False, cache_ttl_hours=24)),
    )
    monkeypatch.setattr(OpsService, "record_model_outcome", lambda **kwargs: None)

    result = asyncio.run(ProviderService.static_generate("hola-cli", {"task_type": "coding"}))

    assert result["provider"] == "codex-main"
    assert result["model"] == "gpt-5-codex"
    assert result["content"] == "CLI_OK:hola-cli"


def test_validate_credentials_codex_account_mode_uses_cli_validation(monkeypatch):
    called = {"cli": False}

    async def _fake_cli_validate(canonical: str):
        called["cli"] = True
        return ProviderValidateResponse(valid=True, health="ok", effective_model="gpt-5-codex", warnings=[])

    async def _should_not_fetch_remote(*args, **kwargs):
        raise AssertionError("remote /models should not be used for codex account mode")

    monkeypatch.setattr(ProviderCatalogService, "_validate_cli_account_provider", _fake_cli_validate)
    monkeypatch.setattr(ProviderCatalogService, "_fetch_remote_models", _should_not_fetch_remote)

    payload = ProviderValidateRequest(account="env:ORCH_PROVIDER_CODEX_ACCOUNT_TOKEN")
    result = asyncio.run(ProviderCatalogService.validate_credentials("codex", payload))

    assert called["cli"] is True
    assert result.valid is True
    assert result.health == "ok"


def test_validate_credentials_openai_api_key_uses_models_endpoint_path(monkeypatch):
    called = {"remote": False, "cli": False}

    async def _fake_remote(provider_type, payload):
        called["remote"] = True
        assert provider_type == "openai"
        assert payload.api_key == "sk-test"
        return [
            NormalizedModelInfo(
                id="gpt-4o",
                label="GPT-4o",
                context_window=128000,
                installed=False,
                downloadable=False,
            )
        ]

    async def _fake_cli_validate(_canonical: str):
        called["cli"] = True
        return ProviderValidateResponse(valid=True, health="ok")

    monkeypatch.setattr(ProviderCatalogService, "_fetch_remote_models", _fake_remote)
    monkeypatch.setattr(ProviderCatalogService, "_validate_cli_account_provider", _fake_cli_validate)

    payload = ProviderValidateRequest(api_key="sk-test")
    result = asyncio.run(ProviderCatalogService.validate_credentials("openai", payload))

    assert called["remote"] is True
    assert called["cli"] is False
    assert result.valid is True


def test_normalize_config_auto_injects_codex_and_claude_account_when_clis_exist(monkeypatch):
    cfg = ProviderConfig(
        active="local-1",
        providers={
            "local-1": ProviderEntry(
                type="openai_compat",
                provider_type="ollama_local",
                auth_mode="none",
                model="qwen2.5-coder:3b",
            )
        },
    )

    monkeypatch.setattr(shutil, "which",
        lambda binary: f"/mock/{binary}" if binary in {"codex", "claude"} else None,
    )

    normalized = ProviderService._normalize_config(cfg)

    assert normalized.active == "local-1"
    assert "codex-account" in normalized.providers
    assert normalized.providers["codex-account"].auth_mode == "account"
    # SAGP: claude-account is no longer auto-injected
    assert "claude-account" not in normalized.providers


def test_normalize_config_does_not_inject_when_clis_missing(monkeypatch):
    cfg = ProviderConfig(
        active="local-1",
        providers={
            "local-1": ProviderEntry(
                type="openai_compat",
                provider_type="ollama_local",
                auth_mode="none",
                model="qwen2.5-coder:3b",
            )
        },
    )

    monkeypatch.setattr(shutil, "which", lambda _binary: None)

    normalized = ProviderService._normalize_config(cfg)

    assert "codex-account" not in normalized.providers
    assert "claude-account" not in normalized.providers


def test_normalize_config_auto_injection_is_idempotent_and_keeps_roles(monkeypatch):
    cfg = ProviderConfig(
        active="local-1",
        providers={
            "local-1": ProviderEntry(
                type="openai_compat",
                provider_type="ollama_local",
                auth_mode="none",
                model="qwen2.5-coder:3b",
            )
        },
    )

    monkeypatch.setattr(shutil, "which",
        lambda binary: f"/mock/{binary}" if binary in {"codex", "claude"} else None,
    )

    first = ProviderService._normalize_config(cfg)
    second = ProviderService._normalize_config(first)

    assert first.active == second.active == "local-1"
    assert first.roles is not None and second.roles is not None
    assert first.roles.orchestrator.provider_id == second.roles.orchestrator.provider_id == "local-1"
    assert list(first.providers.keys()).count("codex-account") == 1
    assert list(second.providers.keys()).count("codex-account") == 1
    # SAGP: claude-account is no longer auto-injected
    assert "claude-account" not in first.providers
    assert "claude-account" not in second.providers


def test_normalize_config_does_not_inject_default_id_when_custom_account_provider_exists(monkeypatch):
    cfg = ProviderConfig(
        active="codex-main",
        providers={
            "codex-main": ProviderEntry(
                type="codex",
                provider_type="codex",
                auth_mode="account",
                model="gpt-5-codex",
            )
        },
    )

    monkeypatch.setattr(shutil, "which",
        lambda binary: f"/mock/{binary}" if binary in {"codex", "claude"} else None,
    )

    normalized = ProviderService._normalize_config(cfg)

    assert "codex-main" in normalized.providers
    assert "codex-account" not in normalized.providers
    assert normalized.active == "codex-main"
