import base64
import json
from pathlib import Path
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from tools.gimo_server.security.integrity import IntegrityVerifier, _sha256_normalized


def _settings(tmp_path: Path, *, enabled: bool = True, manifest_name: str = ".gimo_manifest"):
    return SimpleNamespace(
        integrity_check_enabled=enabled,
        integrity_manifest_path=tmp_path / manifest_name,
        base_dir=tmp_path,
        debug=False,
        integrity_public_key_pem="",
    )


def _signed_payload(manifest: dict, private_key: Ed25519PrivateKey) -> dict:
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(manifest_bytes)
    return {
        "manifest": manifest,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def test_verify_manifest_disabled_is_ok(tmp_path):
    ok, reason = IntegrityVerifier(_settings(tmp_path, enabled=False)).verify_manifest()
    assert ok is True
    assert reason == "disabled"


def test_verify_manifest_missing_is_fail_closed_in_prod(tmp_path):
    ok, reason = IntegrityVerifier(_settings(tmp_path, enabled=True)).verify_manifest()
    assert ok is False
    assert reason == "manifest_missing"


def test_verify_manifest_missing_is_fail_open_only_in_debug(tmp_path):
    settings = _settings(tmp_path, enabled=True)
    settings.debug = True
    ok, reason = IntegrityVerifier(settings).verify_manifest()
    assert ok is True
    assert reason == "manifest_missing_debug_bypass"


def test_verify_manifest_valid(tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text("hello\n", encoding="utf-8")

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode("utf-8")

    manifest = {
        "files": {
            "sample.txt": _sha256_normalized(target),
        }
    }
    settings = _settings(tmp_path)
    settings.integrity_public_key_pem = public_key
    settings.integrity_manifest_path.write_text(json.dumps(_signed_payload(manifest, private_key)), encoding="utf-8")

    ok, reason = IntegrityVerifier(settings).verify_manifest()
    assert ok is True
    assert reason == "ok"


def test_verify_manifest_hash_mismatch(tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text("hello\n", encoding="utf-8")

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode("utf-8")
    manifest = {"files": {"sample.txt": "deadbeef"}}
    settings = _settings(tmp_path)
    settings.integrity_public_key_pem = public_key
    settings.integrity_manifest_path.write_text(json.dumps(_signed_payload(manifest, private_key)), encoding="utf-8")

    ok, reason = IntegrityVerifier(settings).verify_manifest()
    assert ok is False
    assert reason == "hash_mismatch"


def test_verify_manifest_invalid_signature(tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text("hello\n", encoding="utf-8")

    signer = Ed25519PrivateKey.generate()
    wrong_signer = Ed25519PrivateKey.generate()
    public_key = wrong_signer.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode("utf-8")

    manifest = {"files": {"sample.txt": _sha256_normalized(target)}}
    settings = _settings(tmp_path)
    settings.integrity_public_key_pem = public_key
    settings.integrity_manifest_path.write_text(json.dumps(_signed_payload(manifest, signer)), encoding="utf-8")

    ok, reason = IntegrityVerifier(settings).verify_manifest()
    assert ok is False
    assert reason == "invalid_manifest_signature"
