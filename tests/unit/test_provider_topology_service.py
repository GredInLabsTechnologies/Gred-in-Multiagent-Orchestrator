from __future__ import annotations

import json
import shutil

from tools.gimo_server.ops_models import ProviderConfig, ProviderEntry, ProviderRoleBinding, ProviderRolesConfig
from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService
from tools.gimo_server.services.provider_service_impl import ProviderService
from tools.gimo_server.services.provider_topology_service import ProviderTopologyService


def _norm(raw: str | None) -> str:
    return str(raw or "").strip().lower()


def _caps(_ptype: str | None):
    return {"supports_account_mode": True}


def test_inject_cli_account_providers_adds_missing_entries_when_clis_exist(monkeypatch):
    cfg_providers = {
        "local-1": ProviderEntry(
            type="openai_compat",
            provider_type="ollama_local",
            auth_mode="none",
            model="qwen2.5-coder:3b",
        )
    }

    monkeypatch.setattr(
        "tools.gimo_server.services.provider_topology_service.shutil.which",
        lambda binary: f"/mock/{binary}" if binary in {"codex", "claude"} else None,
    )

    out = ProviderTopologyService.inject_cli_account_providers(
        cfg_providers,
        normalize_provider_type=_norm,
        capabilities_for=_caps,
    )

    assert "codex-account" in out
    assert out["codex-account"].auth_mode == "account"
    # SAGP: claude-account is no longer auto-injected (Anthropic April 2026 policy)
    assert "claude-account" not in out


def test_inject_cli_account_providers_no_duplicate_when_custom_account_exists(monkeypatch):
    cfg_providers = {
        "codex-main": ProviderEntry(
            type="codex",
            provider_type="codex",
            auth_mode="account",
            model="gpt-5-codex",
        )
    }

    monkeypatch.setattr(
        "tools.gimo_server.services.provider_topology_service.shutil.which",
        lambda binary: f"/mock/{binary}" if binary in {"codex", "claude"} else None,
    )

    out = ProviderTopologyService.inject_cli_account_providers(
        cfg_providers,
        normalize_provider_type=_norm,
        capabilities_for=_caps,
    )

    assert "codex-main" in out
    assert "codex-account" not in out


def test_normalize_roles_uses_schema_and_deduplicates_worker_equal_to_orchestrator():
    providers = {
        "p1": ProviderEntry(type="openai", provider_type="openai", model="gpt-4o"),
        "p2": ProviderEntry(type="openai", provider_type="openai", model="gpt-4.1"),
    }
    cfg = ProviderConfig(
        active="p1",
        providers=providers,
        roles=ProviderRolesConfig(
            orchestrator=ProviderRoleBinding(provider_id="p1", model="gpt-4o"),
            workers=[
                ProviderRoleBinding(provider_id="p1", model="gpt-4o"),
                ProviderRoleBinding(provider_id="p2", model="gpt-4.1"),
                ProviderRoleBinding(provider_id="p2", model="gpt-4.1"),
            ],
        ),
    )

    roles = ProviderTopologyService.normalize_roles(cfg, providers)

    assert roles.orchestrator.provider_id == "p1"
    assert len(roles.workers) == 1
    assert roles.workers[0].provider_id == "p2"


def test_normalize_roles_falls_back_to_active_when_no_roles_schema():
    providers = {
        "local-1": ProviderEntry(type="openai_compat", provider_type="ollama_local", model="qwen2.5-coder:3b"),
    }
    cfg = ProviderConfig(active="local-1", providers=providers)

    roles = ProviderTopologyService.normalize_roles(cfg, providers)

    assert roles.orchestrator.provider_id == "local-1"
    assert roles.orchestrator.model == "qwen2.5-coder:3b"
    assert roles.workers == []


def test_provider_entry_exposes_configured_model_id_without_collapsing_provider_identity():
    entry = ProviderEntry(
        type="openai",
        provider_type="openai",
        model="gpt-4o-mini",
        model_id="gpt-4.1",
    )

    assert entry.provider_type == "openai"
    assert entry.configured_model_id() == "gpt-4.1"


def test_provider_config_derives_legacy_topology_fields_from_roles():
    cfg = ProviderConfig(
        active="orch-main",
        providers={
            "orch-main": ProviderEntry(type="openai", provider_type="openai", model="gpt-5.4"),
            "worker-1": ProviderEntry(type="openai", provider_type="openai", model="gpt-4o-mini"),
        },
        roles=ProviderRolesConfig(
            orchestrator=ProviderRoleBinding(provider_id="orch-main", model="gpt-5.4"),
            workers=[ProviderRoleBinding(provider_id="worker-1", model="gpt-4o-mini")],
        ),
        orchestrator_provider="legacy-orch",
        orchestrator_model="legacy-model",
        worker_provider="legacy-worker",
        worker_model="legacy-worker-model",
    )

    assert cfg.orchestrator_provider == "orch-main"
    assert cfg.orchestrator_model == "gpt-5.4"
    assert cfg.worker_provider == "worker-1"
    assert cfg.worker_model == "gpt-4o-mini"


def test_ensure_default_config_without_detected_cli_keeps_roles_unset(monkeypatch, tmp_path):
    config_file = tmp_path / "provider.json"

    monkeypatch.setattr("tools.gimo_server.services.providers.service_impl.OPS_DATA_DIR", tmp_path)
    monkeypatch.setattr(ProviderService, "CONFIG_FILE", config_file)
    monkeypatch.setattr(shutil, "which", lambda _binary: None)
    # Block Ollama socket detection (SAGP fallback) and ANTHROPIC_API_KEY
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import socket as _socket
    _orig_create_connection = _socket.create_connection
    monkeypatch.setattr(_socket, "create_connection", lambda *a, **kw: (_ for _ in ()).throw(OSError("mocked")))

    ProviderService.ensure_default_config()

    payload = json.loads(config_file.read_text(encoding="utf-8"))
    cfg = ProviderConfig.model_validate(payload)

    assert cfg.providers == {}
    assert cfg.roles is None


def test_bindings_for_descriptor_prefers_workers_for_execution_tasks():
    providers = {
        "orch-main": ProviderEntry(type="openai", provider_type="openai", model="gpt-5.4"),
        "worker-1": ProviderEntry(type="openai", provider_type="openai", model="gpt-4o-mini"),
    }
    cfg = ProviderConfig(
        active="orch-main",
        providers=providers,
        roles=ProviderRolesConfig(
            orchestrator=ProviderRoleBinding(provider_id="orch-main", model="gpt-5.4"),
            workers=[ProviderRoleBinding(provider_id="worker-1", model="gpt-4o-mini")],
        ),
    )
    descriptor = TaskDescriptorService.descriptor_from_task(
        {
            "id": "t1",
            "title": "Implement fix",
            "description": "Apply code changes in the workspace",
        }
    )

    bindings = ProviderTopologyService.bindings_for_descriptor(cfg, descriptor)

    assert len(bindings) == 1
    assert bindings[0].provider_id == "worker-1"
    assert bindings[0].model == "gpt-4o-mini"


def test_constrain_bindings_keeps_envelope_when_request_is_outside_topology():
    candidates = [
        ProviderRoleBinding(provider_id="worker-1", model="gpt-4o-mini"),
        ProviderRoleBinding(provider_id="worker-2", model="gpt-4.1-mini"),
    ]

    constrained = ProviderTopologyService.constrain_bindings(
        candidates,
        requested_provider="orch-main",
        requested_model="gpt-5.4",
    )

    assert constrained == candidates
