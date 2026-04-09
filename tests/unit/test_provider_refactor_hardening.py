from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tools.gimo_server.ops_models import ProviderEntry
from tools.gimo_server.providers.cli_account import CliAccountAdapter
from tools.gimo_server.providers.openai_compat import OpenAICompatAdapter
from tools.gimo_server.services.providers.connector_service import ProviderConnectorService
from tools.gimo_server.services.providers.metadata import (
    DEFAULT_BASE_URLS,
    OPENAI_COMPAT_ADAPTER_TYPES,
    OPENAI_COMPAT_CATALOG_TYPES,
    REMOTE_MODELS_BASE_URLS,
)
from tools.gimo_server.services.providers.adapter_registry import build_provider_adapter


def test_build_provider_adapter_uses_cli_account_for_codex_account_mode() -> None:
    entry = ProviderEntry(
        type="codex",
        provider_type="codex",
        auth_mode="account",
        model="gpt-5-codex",
    )

    adapter = build_provider_adapter(
        entry=entry,
        canonical_type="codex",
        resolve_secret=lambda _entry: None,
    )

    assert isinstance(adapter, CliAccountAdapter)
    assert adapter.binary == "codex"


def test_build_provider_adapter_openai_uses_default_base_url_and_secret() -> None:
    entry = ProviderEntry(
        type="openai",
        provider_type="openai",
        auth_mode="api_key",
        model="gpt-4o",
    )

    adapter = build_provider_adapter(
        entry=entry,
        canonical_type="openai",
        resolve_secret=lambda _entry: "sk-test",
    )

    assert isinstance(adapter, OpenAICompatAdapter)
    assert adapter.base_url == DEFAULT_BASE_URLS["openai"]
    assert adapter.api_key == "sk-test"


def test_build_provider_adapter_custom_openai_requires_base_url() -> None:
    entry = ProviderEntry(
        type="custom_openai_compatible",
        provider_type="custom_openai_compatible",
        auth_mode="api_key",
        model="custom-model",
    )

    with pytest.raises(ValueError, match="missing base_url"):
        build_provider_adapter(
            entry=entry,
            canonical_type="custom_openai_compatible",
            resolve_secret=lambda _entry: "sk-test",
        )


def test_provider_metadata_contracts_keep_catalog_and_adapter_sets_aligned() -> None:
    # Catalog-discoverable OpenAI-compatible providers should be adapter-compatible too.
    assert OPENAI_COMPAT_CATALOG_TYPES.issubset(OPENAI_COMPAT_ADAPTER_TYPES)

    # Every configured remote catalog URL key should be known by adapter taxonomy.
    assert set(REMOTE_MODELS_BASE_URLS.keys()).issubset(OPENAI_COMPAT_ADAPTER_TYPES | {"anthropic", "claude", "google", "mistral", "cohere"})


def test_get_cli_dependency_install_job_not_found_returns_error_payload() -> None:
    result = ProviderConnectorService.get_cli_dependency_install_job("codex_cli", "missing")
    assert result.status == "error"
    assert "not found" in result.message.lower()


def test_connector_health_unknown_connector_raises() -> None:
    stub = SimpleNamespace(get_config=lambda: None)
    with pytest.raises(ValueError, match="Unknown provider or connector"):
        asyncio.run(ProviderConnectorService.connector_health(stub, "unknown"))


def test_connector_health_openai_compat_uses_provider_health_when_provider_id_present() -> None:
    class _ProviderServiceStub:
        @staticmethod
        async def provider_health(provider_id: str) -> bool:
            return provider_id == "p1"

        @staticmethod
        async def health_check() -> bool:
            return False

        @staticmethod
        def get_config():
            return SimpleNamespace(active="p1", providers={"p1": object(), "p2": object()})

    result = asyncio.run(
        ProviderConnectorService.connector_health(_ProviderServiceStub, "openai_compat", provider_id="p1")
    )

    assert result["id"] == "openai_compat"
    assert result["healthy"] is True
    assert result["details"]["active_provider"] == "p1"
