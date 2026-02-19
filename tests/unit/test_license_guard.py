"""
Tests comprehensivos para LicenseGuard.

Cubre: debug bypass, settings, cache encryption round-trip, grace period,
clock tampering, anti-tamper, fuzzy fingerprint, online validation (mocked),
retry con backoff, _OnlineResponse validation.
"""
import base64
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.gimo_server.security.license_guard import (
    LicenseGuard,
    LicenseStatus,
    _OnlineResponse,
    _aes_decrypt,
    _aes_encrypt,
    _derive_cache_key,
)


def _mk_settings(**overrides):
    base = {
        "license_key": "",
        "license_validate_url": "https://example.test/api/license/validate",
        "license_cache_path": ".gimo_license.test",
        "license_public_key_pem": "",
        "license_grace_days": 7,
        "license_recheck_hours": 24,
        "license_allow_debug_bypass": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_encrypted_cache(fingerprint: str, cache_data: dict) -> bytes:
    """Helper: encrypt cache data with a given fingerprint, return base64-encoded bytes."""
    key = _derive_cache_key(fingerprint)
    raw = json.dumps(cache_data).encode()
    encrypted = _aes_encrypt(raw, key)
    return base64.b64encode(encrypted)


# =====================================================================
# Existing tests (preserved)
# =====================================================================


@pytest.mark.asyncio
async def test_debug_mode_without_key_denied_by_default(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    guard = LicenseGuard(_mk_settings(license_key="", license_allow_debug_bypass=False))

    result = await guard.validate()

    assert result.valid is False
    assert "ORCH_LICENSE_KEY" in result.reason


@pytest.mark.asyncio
async def test_debug_mode_without_key_can_be_enabled_explicitly(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    guard = LicenseGuard(_mk_settings(license_key="", license_allow_debug_bypass=True))

    result = await guard.validate()

    assert result.valid is True
    assert result.reason == "debug_mode"


def test_guard_uses_settings_for_grace_and_recheck():
    guard = LicenseGuard(_mk_settings(license_grace_days=3, license_recheck_hours=12))

    assert guard._grace_period_days == 3
    assert guard._recheck_interval_hours == 12


def test_offline_validation_fails_with_invalid_public_key_format(tmp_path):
    settings = _mk_settings(
        license_key="dummy",
        license_cache_path=str(tmp_path / ".gimo_license"),
        license_public_key_pem="not-a-pem",
    )
    guard = LicenseGuard(settings)

    result = guard._validate_offline()

    assert result.valid is False
    assert "Public key format invalid" in result.reason


# =====================================================================
# AES-256-GCM encryption round-trip
# =====================================================================


def test_aes_encrypt_decrypt_roundtrip():
    """AES-256-GCM encrypt then decrypt should return original plaintext."""
    key = _derive_cache_key("test-fingerprint-abc123")
    plaintext = b'{"token": "jwt.token.here", "last_online_ts": 1708300000}'

    encrypted = _aes_encrypt(plaintext, key)
    decrypted = _aes_decrypt(encrypted, key)

    assert decrypted == plaintext


def test_aes_decrypt_fails_with_wrong_key():
    """Decrypting with a different key should fail (different machine)."""
    key1 = _derive_cache_key("machine-A-fingerprint")
    key2 = _derive_cache_key("machine-B-fingerprint")
    plaintext = b"secret data"

    encrypted = _aes_encrypt(plaintext, key1)

    with pytest.raises(Exception):
        _aes_decrypt(encrypted, key2)


def test_aes_decrypt_fails_with_corrupted_data():
    """Corrupted ciphertext should fail AES-GCM tag verification."""
    key = _derive_cache_key("test-fp")
    encrypted = _aes_encrypt(b"hello", key)

    corrupted = bytearray(encrypted)
    corrupted[-1] ^= 0xFF

    with pytest.raises(Exception):
        _aes_decrypt(bytes(corrupted), key)


# =====================================================================
# Cache save/load round-trip
# =====================================================================


def test_cache_save_and_load_roundtrip(tmp_path):
    """Save cache with one fingerprint, load with same fingerprint should work."""
    cache_path = tmp_path / ".gimo_license"
    settings = _mk_settings(
        license_key="key",
        license_cache_path=str(cache_path),
    )
    guard = LicenseGuard(settings)

    fp = "stable-fingerprint-hash"
    components = {"machine_id": "mid", "mac_address": "mac", "cpu_info": "cpu", "disk_serial": "disk", "username": "usr"}

    # Set cached fingerprint BEFORE save/load to avoid calling real generate_fingerprint
    guard._cached_fingerprint = fp
    guard._save_cache("fake.jwt.token", fp, components)
    assert cache_path.exists()

    loaded = guard._load_cache()

    assert loaded is not None
    assert loaded["token"] == "fake.jwt.token"
    assert loaded["fingerprint_components"] == components


def test_cache_load_fails_different_fingerprint(tmp_path):
    """Cache encrypted with fingerprint A cannot be loaded with fingerprint B."""
    cache_path = tmp_path / ".gimo_license"
    settings = _mk_settings(
        license_key="key",
        license_cache_path=str(cache_path),
    )
    guard = LicenseGuard(settings)

    guard._cached_fingerprint = "fingerprint-A"
    guard._save_cache("jwt", "fingerprint-A", {"machine_id": "a"})

    # Simulate different machine
    guard._cached_fingerprint = "fingerprint-B"
    loaded = guard._load_cache()

    assert loaded is None


# =====================================================================
# Grace period expiry
# =====================================================================


_PEM_KEY = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEApdItyqfVuHkGDXTvzwJrfSSnL3JoXQyWtx8y1hDSA9Y=\n-----END PUBLIC KEY-----"


def test_offline_grace_period_expired(tmp_path):
    """Offline validation should fail when grace period has expired."""
    cache_path = tmp_path / ".gimo_license"
    settings = _mk_settings(
        license_key="key",
        license_cache_path=str(cache_path),
        license_public_key_pem=_PEM_KEY,
        license_grace_days=7,
    )
    guard = LicenseGuard(settings)

    fp = "test-fp"
    old_ts = time.time() - (10 * 86400)  # 10 days ago
    cache_path.write_bytes(_make_encrypted_cache(fp, {
        "token": "fake.jwt",
        "last_online_ts": old_ts,
        "fingerprint_components": {},
        "file_hash": "",
        "guard_version": "1.0.0",
    }))

    guard._cached_fingerprint = fp

    with patch("tools.gimo_server.security.license_guard._verify_jwt_ed25519") as mock_jwt:
        mock_jwt.return_value = {"plan": "standard", "iat": old_ts, "exp": time.time() + 86400}
        result = guard._validate_offline()

    assert result.valid is False
    assert "Grace period expired" in result.reason


def test_offline_grace_period_within_limit(tmp_path):
    """Offline validation should succeed when within grace period."""
    cache_path = tmp_path / ".gimo_license"
    settings = _mk_settings(
        license_key="key",
        license_cache_path=str(cache_path),
        license_public_key_pem=_PEM_KEY,
        license_grace_days=7,
    )
    guard = LicenseGuard(settings)

    fp = "test-fp"
    recent_ts = time.time() - (2 * 86400)  # 2 days ago
    cache_path.write_bytes(_make_encrypted_cache(fp, {
        "token": "valid.jwt",
        "last_online_ts": recent_ts,
        "fingerprint_components": {},
        "file_hash": "",
        "guard_version": "1.0.0",
    }))

    guard._cached_fingerprint = fp

    with patch("tools.gimo_server.security.license_guard._verify_jwt_ed25519") as mock_jwt:
        mock_jwt.return_value = {"plan": "standard", "iat": recent_ts, "exp": time.time() + 86400}
        result = guard._validate_offline()

    assert result.valid is True
    assert "offline_cache" in result.reason


# =====================================================================
# Clock tampering detection
# =====================================================================


def test_offline_clock_tampering_detected(tmp_path):
    """System clock behind JWT iat (>5min) should be detected."""
    cache_path = tmp_path / ".gimo_license"
    settings = _mk_settings(
        license_key="key",
        license_cache_path=str(cache_path),
        license_public_key_pem=_PEM_KEY,
    )
    guard = LicenseGuard(settings)

    fp = "test-fp"
    now = time.time()
    cache_path.write_bytes(_make_encrypted_cache(fp, {
        "token": "jwt",
        "last_online_ts": now,
        "fingerprint_components": {},
        "file_hash": "",
        "guard_version": "1.0.0",
    }))

    guard._cached_fingerprint = fp

    # JWT issued "in the future" (clock was set back)
    future_iat = now + 3600
    with patch("tools.gimo_server.security.license_guard._verify_jwt_ed25519") as mock_jwt:
        mock_jwt.return_value = {"plan": "standard", "iat": future_iat, "exp": future_iat + 86400}
        result = guard._validate_offline()

    assert result.valid is False
    assert "clock tampered" in result.reason.lower()


# =====================================================================
# Anti-tamper detection
# =====================================================================


def test_anti_tamper_detects_modified_file(tmp_path):
    """Same version but different hash should trigger tamper detection."""
    cache_path = tmp_path / ".gimo_license"
    settings = _mk_settings(
        license_key="key",
        license_cache_path=str(cache_path),
    )
    guard = LicenseGuard(settings)

    fp = "test-fp"
    guard._cached_fingerprint = fp

    cache_path.write_bytes(_make_encrypted_cache(fp, {
        "token": "jwt",
        "last_online_ts": time.time(),
        "fingerprint_components": {},
        "file_hash": "fake_stored_hash_that_wont_match",
        "guard_version": "1.0.0",  # Same as current _GUARD_VERSION
    }))

    result = guard._verify_file_integrity()
    assert result is False  # TAMPER detected


def test_anti_tamper_allows_version_update(tmp_path):
    """Different version in cache should be treated as legitimate update."""
    cache_path = tmp_path / ".gimo_license"
    settings = _mk_settings(
        license_key="key",
        license_cache_path=str(cache_path),
    )
    guard = LicenseGuard(settings)

    fp = "test-fp"
    guard._cached_fingerprint = fp

    cache_path.write_bytes(_make_encrypted_cache(fp, {
        "token": "jwt",
        "last_online_ts": time.time(),
        "fingerprint_components": {},
        "file_hash": "old_hash",
        "guard_version": "0.9.0",  # Different from current _GUARD_VERSION
    }))

    result = guard._verify_file_integrity()
    assert result is True
    assert guard._guard_version_updated is True


def test_anti_tamper_no_cache_first_boot(tmp_path):
    """First boot (no cache) should pass integrity check."""
    cache_path = tmp_path / ".gimo_license_nonexistent"
    settings = _mk_settings(
        license_key="key",
        license_cache_path=str(cache_path),
    )
    guard = LicenseGuard(settings)

    result = guard._verify_file_integrity()
    assert result is True


# =====================================================================
# Fuzzy fingerprint matching (offline validation)
# =====================================================================


def test_offline_fingerprint_mismatch_rejects(tmp_path):
    """All 5 signals different should reject (0/5 match, below 60% threshold)."""
    cache_path = tmp_path / ".gimo_license"
    settings = _mk_settings(
        license_key="key",
        license_cache_path=str(cache_path),
        license_public_key_pem=_PEM_KEY,
    )
    guard = LicenseGuard(settings)

    fp = "test-fp"
    stored_components = {
        "machine_id": "old-mid",
        "mac_address": "old-mac",
        "cpu_info": "old-cpu",
        "disk_serial": "old-disk",
        "username": "old-user",
    }
    now = time.time()
    cache_path.write_bytes(_make_encrypted_cache(fp, {
        "token": "jwt",
        "last_online_ts": now,
        "fingerprint_components": stored_components,
        "file_hash": "",
        "guard_version": "1.0.0",
    }))

    guard._cached_fingerprint = fp

    different_components = {
        "machine_id": "new-mid",
        "mac_address": "new-mac",
        "cpu_info": "new-cpu",
        "disk_serial": "new-disk",
        "username": "new-user",
    }

    with patch("tools.gimo_server.security.license_guard._verify_jwt_ed25519") as mock_jwt, \
         patch("tools.gimo_server.security.fingerprint.generate_fingerprint_components", return_value=different_components), \
         patch("tools.gimo_server.security.fingerprint.compare_fingerprints", return_value=False):
        mock_jwt.return_value = {"plan": "standard", "iat": now, "exp": now + 86400}
        result = guard._validate_offline()

    assert result.valid is False
    assert "fingerprint mismatch" in result.reason.lower()


# =====================================================================
# _OnlineResponse validation
# =====================================================================


def test_online_response_from_dict_valid():
    data = {
        "valid": True,
        "token": "jwt.token.here",
        "plan": "standard",
        "expiresAt": "2026-04-17T00:00:00Z",
        "isLifetime": False,
        "activeInstallations": 1,
        "maxInstallations": 2,
    }
    resp = _OnlineResponse.from_dict(data)
    assert resp.valid is True
    assert resp.token == "jwt.token.here"
    assert resp.plan == "standard"
    assert resp.activeInstallations == 1
    assert resp.maxInstallations == 2


def test_online_response_from_dict_missing_fields():
    """Missing fields should use defaults, not crash."""
    data = {"valid": False, "error": "license_expired"}
    resp = _OnlineResponse.from_dict(data)
    assert resp.valid is False
    assert resp.token == ""
    assert resp.plan == "standard"
    assert resp.error == "license_expired"
    assert resp.maxInstallations == 2


def test_online_response_from_dict_empty():
    """Empty dict should produce safe defaults."""
    resp = _OnlineResponse.from_dict({})
    assert resp.valid is False
    assert resp.token == ""


# =====================================================================
# Online validation with mocked httpx (retry behavior)
# =====================================================================


@pytest.mark.asyncio
async def test_online_validation_success(tmp_path):
    """Successful online validation should return valid status and save cache."""
    cache_path = tmp_path / ".gimo_license"
    settings = _mk_settings(
        license_key="test-key-123",
        license_cache_path=str(cache_path),
    )
    guard = LicenseGuard(settings)
    guard._cached_fingerprint = "fp-hash"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "valid": True,
        "token": "signed.jwt.token",
        "plan": "standard",
        "expiresAt": "2026-04-17",
        "isLifetime": False,
        "activeInstallations": 1,
        "maxInstallations": 2,
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.post = AsyncMock(return_value=mock_response)

    with patch("tools.gimo_server.security.fingerprint.generate_fingerprint", return_value="fp-hash"), \
         patch("tools.gimo_server.security.fingerprint.generate_fingerprint_components", return_value={"machine_id": "m"}), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await guard._validate_online()

    assert result.valid is True
    assert result.plan == "standard"
    assert result.installations_used == 1


@pytest.mark.asyncio
async def test_online_validation_rejection_no_retry(tmp_path):
    """Server rejection (valid=false) should NOT retry."""
    settings = _mk_settings(
        license_key="test-key",
        license_cache_path=str(tmp_path / ".gimo_license"),
    )
    guard = LicenseGuard(settings)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"valid": False, "error": "license_expired"}

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return mock_response

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post

    with patch("tools.gimo_server.security.fingerprint.generate_fingerprint", return_value="fp"), \
         patch("tools.gimo_server.security.fingerprint.generate_fingerprint_components", return_value={}), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await guard._validate_online()

    assert result.valid is False
    assert result.reason == "license_expired"
    assert call_count == 1


@pytest.mark.asyncio
async def test_online_validation_retry_on_network_error(tmp_path):
    """Network errors should trigger retries with backoff."""
    import httpx

    settings = _mk_settings(
        license_key="test-key",
        license_cache_path=str(tmp_path / ".gimo_license"),
    )
    guard = LicenseGuard(settings)
    guard._RETRY_BASE_DELAY = 0.01

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("Connection refused")

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post

    with patch("tools.gimo_server.security.fingerprint.generate_fingerprint", return_value="fp"), \
         patch("tools.gimo_server.security.fingerprint.generate_fingerprint_components", return_value={}), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(httpx.ConnectError):
            await guard._validate_online()

    assert call_count == 3


@pytest.mark.asyncio
async def test_online_validation_retry_on_http_500(tmp_path):
    """HTTP 500 should trigger retries."""
    settings = _mk_settings(
        license_key="test-key",
        license_cache_path=str(tmp_path / ".gimo_license"),
    )
    guard = LicenseGuard(settings)
    guard._RETRY_BASE_DELAY = 0.01

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return mock_response

    mock_client_instance = AsyncMock()
    mock_client_instance.post = mock_post

    with patch("tools.gimo_server.security.fingerprint.generate_fingerprint", return_value="fp"), \
         patch("tools.gimo_server.security.fingerprint.generate_fingerprint_components", return_value={}), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ConnectionError, match="HTTP 500"):
            await guard._validate_online()

    assert call_count == 3


# =====================================================================
# Offline: placeholder key detection
# =====================================================================


def test_offline_rejects_placeholder_key(tmp_path):
    settings = _mk_settings(
        license_key="key",
        license_cache_path=str(tmp_path / ".gimo_license"),
        license_public_key_pem="PLACEHOLDER_KEY",
    )
    guard = LicenseGuard(settings)
    result = guard._validate_offline()

    assert result.valid is False
    assert "Public key not configured" in result.reason


def test_offline_no_cache_file(tmp_path):
    settings = _mk_settings(
        license_key="key",
        license_cache_path=str(tmp_path / "nonexistent"),
        license_public_key_pem=_PEM_KEY,
    )
    guard = LicenseGuard(settings)
    result = guard._validate_offline()

    assert result.valid is False
    assert "No valid offline cache" in result.reason


# =====================================================================
# Fingerprint module tests
# =====================================================================


def test_compare_fingerprints_same_machine():
    from tools.gimo_server.security.fingerprint import compare_fingerprints

    components = {
        "machine_id": "abc",
        "mac_address": "aa:bb:cc",
        "cpu_info": "Intel i7",
        "disk_serial": "DISK123",
        "username": "admin",
    }
    assert compare_fingerprints(components, components) is True


def test_compare_fingerprints_two_signals_changed():
    """2 of 5 signals changed (60% match) should still pass threshold."""
    from tools.gimo_server.security.fingerprint import compare_fingerprints

    stored = {
        "machine_id": "abc",
        "mac_address": "aa:bb:cc",
        "cpu_info": "Intel i7",
        "disk_serial": "DISK123",
        "username": "admin",
    }
    current = {
        "machine_id": "abc",
        "mac_address": "CHANGED",
        "cpu_info": "Intel i7",
        "disk_serial": "DISK123",
        "username": "CHANGED",
    }
    assert compare_fingerprints(stored, current, threshold=0.6) is True


def test_compare_fingerprints_three_signals_changed():
    """3 of 5 signals changed (40% match) should fail threshold."""
    from tools.gimo_server.security.fingerprint import compare_fingerprints

    stored = {
        "machine_id": "abc",
        "mac_address": "aa:bb:cc",
        "cpu_info": "Intel i7",
        "disk_serial": "DISK123",
        "username": "admin",
    }
    current = {
        "machine_id": "CHANGED",
        "mac_address": "CHANGED",
        "cpu_info": "Intel i7",
        "disk_serial": "CHANGED",
        "username": "admin",
    }
    assert compare_fingerprints(stored, current, threshold=0.6) is False


def test_compare_fingerprints_empty_signals_not_counted():
    """Empty signals on both sides should not count as match or mismatch."""
    from tools.gimo_server.security.fingerprint import compare_fingerprints

    stored = {
        "machine_id": "abc",
        "mac_address": "",
        "cpu_info": "",
        "disk_serial": "DISK123",
        "username": "",
    }
    current = {
        "machine_id": "abc",
        "mac_address": "",
        "cpu_info": "",
        "disk_serial": "DISK123",
        "username": "",
    }
    assert compare_fingerprints(stored, current) is True


# =====================================================================
# derive_cache_key determinism
# =====================================================================


def test_derive_cache_key_deterministic():
    """Same fingerprint should always produce the same key."""
    key1 = _derive_cache_key("fingerprint-xyz")
    key2 = _derive_cache_key("fingerprint-xyz")
    assert key1 == key2
    assert len(key1) == 32


def test_derive_cache_key_different_fingerprints():
    """Different fingerprints should produce different keys."""
    key1 = _derive_cache_key("fp-A")
    key2 = _derive_cache_key("fp-B")
    assert key1 != key2
