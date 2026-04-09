from __future__ import annotations

from tools.gimo_server.ops_models import ProviderConfig, ProviderEntry
from tools.gimo_server.services.providers.config_change_service import ProviderConfigChangeService


def _norm(raw: str | None) -> str:
    return str(raw or "").strip().lower()


def test_get_changed_provider_types_includes_all_on_first_snapshot():
    current = ProviderConfig(
        active="p1",
        providers={
            "p1": ProviderEntry(type="openai", provider_type="openai", model="gpt-4o"),
            "p2": ProviderEntry(type="codex", provider_type="codex", model="gpt-5-codex", auth_mode="account"),
        },
    )

    called: list[tuple[str, str]] = []
    changed = ProviderConfigChangeService.get_changed_provider_types(
        before=None,
        current=current,
        normalize_provider_type=_norm,
        invalidate_catalog_cache=lambda provider_type, reason: called.append((provider_type, reason)),
    )

    assert changed == {"openai", "codex"}
    assert called == []


def test_compare_provider_invalidates_on_credential_change():
    prev = ProviderEntry(type="openai", provider_type="openai", model="gpt-4o", auth_mode="api_key", auth_ref="env:OLD")
    cur = ProviderEntry(type="openai", provider_type="openai", model="gpt-4o", auth_mode="api_key", auth_ref="env:NEW")
    changed_types: set[str] = set()
    called: list[tuple[str, str]] = []

    ProviderConfigChangeService.compare_provider(
        prev=prev,
        cur=cur,
        changed_types=changed_types,
        normalize_provider_type=_norm,
        invalidate_catalog_cache=lambda provider_type, reason: called.append((provider_type, reason)),
    )

    assert "openai" in changed_types
    assert called == [("openai", "credentials_changed")]


def test_get_changed_provider_types_detects_added_removed_and_updated_entries():
    before = ProviderConfig(
        active="p1",
        providers={
            "p1": ProviderEntry(type="openai", provider_type="openai", model="gpt-4o", auth_mode="api_key", auth_ref="env:OPENAI"),
            "p2": ProviderEntry(type="claude", provider_type="claude", model="claude-3-7-sonnet-latest", auth_mode="account"),
        },
    )
    current = ProviderConfig(
        active="p3",
        providers={
            "p1": ProviderEntry(type="openai", provider_type="openai", model="gpt-4.1", auth_mode="api_key", auth_ref="env:OPENAI2"),
            "p3": ProviderEntry(type="codex", provider_type="codex", model="gpt-5-codex", auth_mode="account"),
        },
    )

    invalidations: list[tuple[str, str]] = []
    changed = ProviderConfigChangeService.get_changed_provider_types(
        before=before,
        current=current,
        normalize_provider_type=_norm,
        invalidate_catalog_cache=lambda provider_type, reason: invalidations.append((provider_type, reason)),
    )

    assert changed == {"openai", "claude", "codex"}
    assert ("openai", "credentials_changed") in invalidations
