"""Tests for the encrypted provider secret store (Change 3)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest


# Stable test fingerprint — deterministic key derivation
_TEST_FINGERPRINT = "test-fingerprint-for-secret-store-unit-tests"


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    """Redirect store to tmp dir and use stable fingerprint."""
    store_path = tmp_path / "provider_secrets.enc"
    monkeypatch.setattr(
        "tools.gimo_server.services.providers.secret_store._store_path",
        lambda: store_path,
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.providers.secret_store._derive_key",
        lambda: _derive_test_key(),
    )
    return store_path


def _derive_test_key() -> bytes:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"GIMO-TEST-SECRET-STORE",
        iterations=1,  # Fast for tests
    )
    return kdf.derive(_TEST_FINGERPRINT.encode())


class TestSecretStore:
    def test_set_and_get_secret(self):
        from tools.gimo_server.services.providers.secret_store import set_secret, get_secret

        set_secret("ORCH_PROVIDER_OPENAI_API_KEY", "sk-test-123")
        assert get_secret("ORCH_PROVIDER_OPENAI_API_KEY") == "sk-test-123"

    def test_persist_across_loads(self):
        from tools.gimo_server.services.providers.secret_store import set_secret, get_secret, load_secrets

        set_secret("KEY", "value")
        # Force re-read from disk
        assert load_secrets().get("KEY") == "value"

    def test_delete_secret(self):
        from tools.gimo_server.services.providers.secret_store import set_secret, get_secret, delete_secret

        set_secret("KEY", "value")
        assert delete_secret("KEY") is True
        assert get_secret("KEY") is None

    def test_delete_nonexistent_returns_false(self):
        from tools.gimo_server.services.providers.secret_store import delete_secret

        assert delete_secret("NOPE") is False

    def test_corrupt_file_returns_empty(self, _isolate_store):
        from tools.gimo_server.services.providers.secret_store import load_secrets

        _isolate_store.write_bytes(b"this is not valid base64 or encrypted data")
        assert load_secrets() == {}

    def test_missing_file_returns_empty(self, _isolate_store):
        from tools.gimo_server.services.providers.secret_store import load_secrets

        if _isolate_store.exists():
            _isolate_store.unlink()
        assert load_secrets() == {}

    def test_multiple_secrets(self):
        from tools.gimo_server.services.providers.secret_store import set_secret, get_secret

        set_secret("A", "1")
        set_secret("B", "2")
        assert get_secret("A") == "1"
        assert get_secret("B") == "2"

    def test_overwrite_secret(self):
        from tools.gimo_server.services.providers.secret_store import set_secret, get_secret

        set_secret("KEY", "old")
        set_secret("KEY", "new")
        assert get_secret("KEY") == "new"


class TestSecretStoreIntegration:
    def test_resolve_prefers_vault_over_env(self, monkeypatch):
        from tools.gimo_server.services.providers.secret_store import set_secret
        from tools.gimo_server.services.providers.auth_service import ProviderAuthService

        set_secret("ORCH_PROVIDER_X_API_KEY", "from-vault")
        monkeypatch.setenv("ORCH_PROVIDER_X_API_KEY", "from-env")

        # Create a minimal ProviderEntry-like object
        class FakeEntry:
            auth_ref = "env:ORCH_PROVIDER_X_API_KEY"
            api_key = None

        result = ProviderAuthService.resolve_secret(FakeEntry())
        assert result == "from-vault"

    def test_resolve_falls_back_to_env(self, monkeypatch):
        from tools.gimo_server.services.providers.auth_service import ProviderAuthService

        # No vault entry
        monkeypatch.setenv("ORCH_PROVIDER_Y_API_KEY", "from-env")

        class FakeEntry:
            auth_ref = "env:ORCH_PROVIDER_Y_API_KEY"
            api_key = None

        result = ProviderAuthService.resolve_secret(FakeEntry())
        assert result == "from-env"
