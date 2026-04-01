from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import pytest

from tools.gimo_server.security.cold_room import ColdRoomManager
from tools.gimo_server.security.license_guard import LicenseGuard

# Save the real validate method before session-scoped mocks can replace it.
_REAL_VALIDATE = LicenseGuard.validate


@pytest.fixture(autouse=True)
def _restore_real_validate():
    """Undo session-scoped LicenseGuard.validate mock so cold_room tests use real logic."""
    LicenseGuard.validate = _REAL_VALIDATE
    yield
    # No need to restore mock — the session mock will re-apply on next test_client usage.


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _settings(tmp_path, public_key_pem: str, *, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        cold_room_enabled=enabled,
        cold_room_license_path=tmp_path / ".gimo_cold_room_test",
        cold_room_public_key_pem=public_key_pem,
        cold_room_renewal_days=30,
        # campos usados por LicenseGuard
        license_key="TEST-LICENSE-KEY-123",
        license_validate_url="https://example.invalid/license/validate",
        license_cache_path=str(tmp_path / ".gimo_license_test"),
        license_grace_days=3,
        license_recheck_hours=24,
        license_allow_debug_bypass=False,
        license_public_key_pem=None,
    )


def _build_blob(
    private_key: Ed25519PrivateKey,
    *,
    machine_id: str,
    expires_in_seconds: int,
    plan: str = "cold_room",
    features: list[str] | None = None,
    renewals_remaining: int = 3,
) -> str:
    payload = {
        "v": 2,
        "mid": machine_id,
        "exp": int(time.time()) + expires_in_seconds,
        "plan": plan,
        "feat": features or ["offline", "airgap"],
        "rnw": renewals_remaining,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = private_key.sign(payload_bytes)
    return _b64url(payload_bytes + signature)


def test_activate_and_status_roundtrip(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    s = _settings(tmp_path, public_key_pem)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        manager = ColdRoomManager(s)
        blob = _build_blob(private_key, machine_id=manager.get_machine_id(), expires_in_seconds=7 * 86400)

        ok, reason = manager.activate(blob)
        assert ok is True
        assert reason == "ok"
        assert manager.is_paired() is True
        assert manager.is_renewal_valid() is True

        status = manager.get_status()
        assert status["paired"] is True
        assert status["vm_detected"] is False
        assert status["renewal_valid"] is True
        assert status["renewal_needed"] is False
        assert status["machine_id"].startswith("GIMO-")
        assert isinstance(status.get("features"), list)


def test_activate_rejects_machine_mismatch(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    s = _settings(tmp_path, public_key_pem)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        manager = ColdRoomManager(s)
        blob = _build_blob(private_key, machine_id="GIMO-FAKE-0000", expires_in_seconds=7 * 86400)
        ok, reason = manager.activate(blob)
        assert ok is False
        assert reason == "machine_mismatch"


def test_expired_blob_marks_renewal_needed_in_status(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    s = _settings(tmp_path, public_key_pem)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        manager = ColdRoomManager(s)

        valid_blob = _build_blob(private_key, machine_id=manager.get_machine_id(), expires_in_seconds=7 * 86400)
        ok, _ = manager.activate(valid_blob)
        assert ok is True

        expired_blob = _build_blob(private_key, machine_id=manager.get_machine_id(), expires_in_seconds=-3600)
        raw = manager._load_state()
        assert raw is not None
        raw["license_blob"] = expired_blob
        raw["updated_at"] = time.time()
        manager._save_state(raw)

        assert manager.is_paired() is True
        assert manager.is_renewal_valid() is False

        status = manager.get_status()
        assert status["paired"] is False
        assert status["vm_detected"] is False
        assert status["renewal_valid"] is False
        assert status["renewal_needed"] is True


def test_get_info_unpaired(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    s = _settings(tmp_path, public_key_pem)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        manager = ColdRoomManager(s)
        info = manager.get_info()
        assert info["paired"] is False
        assert info["machine_id"].startswith("GIMO-")


def test_license_guard_uses_cold_room_when_valid(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    s = _settings(tmp_path, public_key_pem, enabled=True)

    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        manager = ColdRoomManager(s)
        blob = _build_blob(private_key, machine_id=manager.get_machine_id(), expires_in_seconds=7 * 86400)
        ok, _ = manager.activate(blob)
        assert ok is True

    guard = LicenseGuard(s)
    with patch("tools.gimo_server.config.get_settings", return_value=s), patch(
        "tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"
    ):
        import asyncio

        result = asyncio.run(guard.validate())

    assert result.valid is True
    assert result.plan == "cold_room"
    assert result.reason == "cold_room_active"


def test_license_guard_returns_renewal_required_when_expired(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    s = _settings(tmp_path, public_key_pem, enabled=True)

    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        manager = ColdRoomManager(s)
        valid_blob = _build_blob(private_key, machine_id=manager.get_machine_id(), expires_in_seconds=7 * 86400)
        ok, _ = manager.activate(valid_blob)
        assert ok is True

        expired_blob = _build_blob(private_key, machine_id=manager.get_machine_id(), expires_in_seconds=-3600)
        raw = manager._load_state()
        assert raw is not None
        raw["license_blob"] = expired_blob
        raw["updated_at"] = time.time()
        manager._save_state(raw)

    guard = LicenseGuard(s)
    with patch("tools.gimo_server.config.get_settings", return_value=s), patch(
        "tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"
    ):
        import asyncio

        result = asyncio.run(guard.validate())

    assert result.valid is False
    assert result.reason == "cold_room_renewal_required"


def test_activate_rejects_nonce_replay(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    s = _settings(tmp_path, public_key_pem)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        manager = ColdRoomManager(s)
        payload = {
            "v": 2,
            "mid": manager.get_machine_id(),
            "exp": int(time.time()) + 86400,
            "plan": "cold_room",
            "feat": ["offline"],
            "rnw": 2,
            "nonce": "nonce-1",
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        blob = _b64url(payload_bytes + private_key.sign(payload_bytes))

        ok, reason = manager.activate(blob)
        assert ok is True
        assert reason == "ok"

        ok2, reason2 = manager.activate(blob)
        assert ok2 is False
        assert reason2 == "nonce_replay_detected"


def test_activate_rejects_invalid_nonce_type(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    s = _settings(tmp_path, public_key_pem)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        manager = ColdRoomManager(s)
        payload = {
            "v": 2,
            "mid": manager.get_machine_id(),
            "exp": int(time.time()) + 86400,
            "plan": "cold_room",
            "feat": ["offline"],
            "rnw": 2,
            "nonce": 1234,
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        blob = _b64url(payload_bytes + private_key.sign(payload_bytes))

        ok, reason = manager.activate(blob)
        assert ok is False
        assert reason == "invalid_nonce"


# ---------------------------------------------------------------------------
# Helpers reutilizables para los tests adicionales
# ---------------------------------------------------------------------------

def _make_manager(tmp_path):
    """Crea un par de claves y un ColdRoomManager configurado para tests."""
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    s = _settings(tmp_path, public_key_pem)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        manager = ColdRoomManager(s)
    return private_key, manager


# ---------------------------------------------------------------------------
# Tests adicionales alineados al plan
# ---------------------------------------------------------------------------


def test_machine_id_deterministic(tmp_path):
    """Mismo fingerprint produce el mismo Machine ID."""
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    s = _settings(tmp_path, pem)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-stable"):
        m1 = ColdRoomManager(s)
        m2 = ColdRoomManager(s)
    assert m1.get_machine_id() == m2.get_machine_id()


def test_machine_id_format(tmp_path):
    """Machine ID tiene formato GIMO-XXXX-XXXX."""
    _, manager = _make_manager(tmp_path)
    mid = manager.get_machine_id()
    assert mid.startswith("GIMO-")
    parts = mid.split("-")
    assert len(parts) == 3
    assert len(parts[1]) == 4
    assert len(parts[2]) == 4


def test_activate_rejects_invalid_signature(tmp_path):
    """Blob firmado con otra clave es rechazado."""
    _, manager = _make_manager(tmp_path)
    other_key = Ed25519PrivateKey.generate()
    blob = _build_blob(other_key, machine_id=manager.get_machine_id(), expires_in_seconds=86400)

    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        ok, reason = manager.activate(blob)
    assert ok is False
    assert reason == "invalid_signature"


def test_activate_rejects_wrong_version(tmp_path):
    """Blob con version != 2 es rechazado."""
    private_key, manager = _make_manager(tmp_path)
    payload = {
        "v": 1,
        "mid": manager.get_machine_id(),
        "exp": int(time.time()) + 86400,
        "plan": "cold_room",
        "feat": ["offline"],
        "rnw": 2,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    blob = _b64url(payload_bytes + private_key.sign(payload_bytes))

    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        ok, reason = manager.activate(blob)
    assert ok is False
    assert reason == "unsupported_license_version"


def test_is_paired_before_activate(tmp_path):
    """Antes de activar, is_paired devuelve False."""
    _, manager = _make_manager(tmp_path)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        assert manager.is_paired() is False


def test_is_paired_after_activate(tmp_path):
    """Despues de activar, is_paired devuelve True."""
    private_key, manager = _make_manager(tmp_path)
    blob = _build_blob(private_key, machine_id=manager.get_machine_id(), expires_in_seconds=86400)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        ok, _ = manager.activate(blob)
        assert ok is True
        assert manager.is_paired() is True


def test_features_extracted(tmp_path):
    """Las features del blob aparecen en status."""
    private_key, manager = _make_manager(tmp_path)
    custom_features = ["orchestration", "eval", "mastery"]
    blob = _build_blob(
        private_key,
        machine_id=manager.get_machine_id(),
        expires_in_seconds=86400,
        features=custom_features,
    )
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        ok, _ = manager.activate(blob)
        assert ok is True
        status = manager.get_status()
    assert status["features"] == custom_features


def test_renewals_remaining_extracted(tmp_path):
    """renewals_remaining del blob aparece en status."""
    private_key, manager = _make_manager(tmp_path)
    blob = _build_blob(
        private_key,
        machine_id=manager.get_machine_id(),
        expires_in_seconds=86400,
        renewals_remaining=7,
    )
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        ok, _ = manager.activate(blob)
        assert ok is True
        status = manager.get_status()
    assert status["renewals_remaining"] == 7


def test_state_persistence_encrypted(tmp_path):
    """El state file no contiene JSON legible (esta cifrado + base64)."""
    private_key, manager = _make_manager(tmp_path)
    blob = _build_blob(private_key, machine_id=manager.get_machine_id(), expires_in_seconds=86400)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        ok, _ = manager.activate(blob)
        assert ok is True

    state_path = tmp_path / ".gimo_cold_room_test"
    assert state_path.exists()
    raw_content = state_path.read_text()
    # El contenido es base64 de AES cifrado, no JSON plano
    try:
        parsed = json.loads(raw_content)
        # Si se parsea como JSON, el state NO esta cifrado -> fallo
        assert False, "State file should be encrypted, not plain JSON"
    except (json.JSONDecodeError, ValueError):
        pass  # Correcto: no es JSON legible


def test_state_tamper_detected(tmp_path):
    """Corromper el archivo de state causa que _load_state retorne None."""
    private_key, manager = _make_manager(tmp_path)
    blob = _build_blob(private_key, machine_id=manager.get_machine_id(), expires_in_seconds=86400)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        ok, _ = manager.activate(blob)
        assert ok is True
        assert manager.is_paired() is True

    state_path = tmp_path / ".gimo_cold_room_test"
    state_path.write_text("CORRUPTED_DATA_HERE")

    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        assert manager.is_paired() is False


def test_empty_blob_rejected(tmp_path):
    """Blob vacio es rechazado."""
    _, manager = _make_manager(tmp_path)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        ok, reason = manager.activate("")
    assert ok is False
    assert reason == "empty_license_blob"


def test_invalid_encoding_rejected(tmp_path):
    """Blob con encoding invalido es rechazado."""
    _, manager = _make_manager(tmp_path)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        ok, reason = manager.activate("!!!not-base64!!!")
    assert ok is False
    assert reason in ("invalid_blob_encoding", "invalid_blob_size")


def test_short_blob_rejected(tmp_path):
    """Blob demasiado corto (<=64 bytes decoded) es rechazado."""
    _, manager = _make_manager(tmp_path)
    short = _b64url(b"tooshort")
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        ok, reason = manager.activate(short)
    assert ok is False
    assert reason == "invalid_blob_size"


def test_get_info_paired(tmp_path):
    """get_info retorna datos completos cuando la licencia es valida."""
    private_key, manager = _make_manager(tmp_path)
    blob = _build_blob(
        private_key,
        machine_id=manager.get_machine_id(),
        expires_in_seconds=86400,
        plan="enterprise_cold_room",
        features=["orchestration", "eval"],
        renewals_remaining=5,
    )
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        ok, _ = manager.activate(blob)
        assert ok is True
        info = manager.get_info()
    assert info["paired"] is True
    assert info["plan"] == "enterprise_cold_room"
    assert info["features"] == ["orchestration", "eval"]
    assert info["renewals_remaining"] == 5
    assert info["days_remaining"] >= 0
    assert "expires_at" in info


def test_cold_room_disabled(tmp_path):
    """ColdRoomManager con enabled=False no activa nada."""
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    s = _settings(tmp_path, pem, enabled=False)
    with patch("tools.gimo_server.security.cold_room.generate_fingerprint", return_value="fp-unit-test"):
        manager = ColdRoomManager(s)
    assert manager._enabled is False
