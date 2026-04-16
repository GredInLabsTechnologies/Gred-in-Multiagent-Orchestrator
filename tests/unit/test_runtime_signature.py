"""Tests de firma Ed25519 del runtime.

Step 1 del plan RUNTIME_PACKAGING — en este step los tests fallan con
``NotImplementedError`` porque ``runtime_signature.py`` está en modo stub.
Step 2 aterriza la implementación y estos tests deben ponerse verdes.
"""
from __future__ import annotations

import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from tools.gimo_server.models.runtime import (
    RuntimeCompression,
    RuntimeManifest,
    RuntimeTarget,
)
from tools.gimo_server.security import runtime_signature


@pytest.fixture
def keypair_pem() -> tuple[str, str]:
    """Par Ed25519 efímero en PEM para tests."""
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_pem = priv.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode("utf-8")
    pub_pem = pub.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


@pytest.fixture
def unsigned_manifest() -> RuntimeManifest:
    """Manifest válido en schema pero con firma placeholder (no verificable)."""
    return RuntimeManifest(
        runtime_version="0.1.0",
        target=RuntimeTarget.android_arm64,
        compression=RuntimeCompression.xz,
        tarball_name="gimo-core-runtime.tar.xz",
        tarball_sha256="a" * 64,
        compressed_size_bytes=13_000_000,
        uncompressed_size_bytes=45_000_000,
        python_rel_path="python/bin/python3.11",
        repo_root_rel_path="repo",
        python_path_entries=["repo", "site-packages"],
        files=["python/bin/python3.11"],
        extra_env={},
        signature="0" * 128,  # placeholder — se reemplaza con firma real
    )


class TestSignAndVerify:
    def test_sign_produces_hex_128(self, keypair_pem, unsigned_manifest):
        priv_pem, _pub_pem = keypair_pem
        sig = runtime_signature.sign_manifest(unsigned_manifest, priv_pem)
        assert isinstance(sig, str)
        assert len(sig) == 128
        assert all(c in "0123456789abcdef" for c in sig)

    def test_verify_accepts_own_signature(self, keypair_pem, unsigned_manifest):
        priv_pem, pub_pem = keypair_pem
        sig = runtime_signature.sign_manifest(unsigned_manifest, priv_pem)
        signed = unsigned_manifest.model_copy(update={"signature": sig})
        assert runtime_signature.verify_manifest(signed, pub_pem) is True

    def test_verify_rejects_tampered_hash(self, keypair_pem, unsigned_manifest):
        """Flipping el tarball_sha256 invalida la firma."""
        priv_pem, pub_pem = keypair_pem
        sig = runtime_signature.sign_manifest(unsigned_manifest, priv_pem)
        tampered = unsigned_manifest.model_copy(
            update={"signature": sig, "tarball_sha256": "f" * 64}
        )
        assert runtime_signature.verify_manifest(tampered, pub_pem) is False

    def test_verify_rejects_tampered_version(self, keypair_pem, unsigned_manifest):
        """Cambiar runtime_version invalida la firma."""
        priv_pem, pub_pem = keypair_pem
        sig = runtime_signature.sign_manifest(unsigned_manifest, priv_pem)
        tampered = unsigned_manifest.model_copy(
            update={"signature": sig, "runtime_version": "0.1.1"}
        )
        assert runtime_signature.verify_manifest(tampered, pub_pem) is False

    def test_verify_rejects_tampered_target(self, keypair_pem, unsigned_manifest):
        """Cambiar target invalida la firma — evita cross-target spoofing."""
        priv_pem, pub_pem = keypair_pem
        sig = runtime_signature.sign_manifest(unsigned_manifest, priv_pem)
        tampered = unsigned_manifest.model_copy(
            update={"signature": sig, "target": RuntimeTarget.windows_x86_64}
        )
        assert runtime_signature.verify_manifest(tampered, pub_pem) is False

    def test_verify_rejects_wrong_key(self, keypair_pem, unsigned_manifest):
        """Firma hecha con keypair A no verifica con pub key B."""
        priv_pem_a, _pub_pem_a = keypair_pem
        # Generar segundo keypair independiente
        priv_b = Ed25519PrivateKey.generate()
        pub_pem_b = priv_b.public_key().public_bytes(
            encoding=Encoding.PEM,
            format=PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        sig = runtime_signature.sign_manifest(unsigned_manifest, priv_pem_a)
        signed = unsigned_manifest.model_copy(update={"signature": sig})
        assert runtime_signature.verify_manifest(signed, pub_pem_b) is False


class TestSignErrors:
    def test_invalid_private_key_raises(self, unsigned_manifest):
        with pytest.raises(runtime_signature.RuntimeSignatureError):
            runtime_signature.sign_manifest(unsigned_manifest, "NOT A PEM")


class TestSha256File:
    def test_sha256_file_matches_hashlib(self, tmp_path):
        target = tmp_path / "sample.bin"
        data = b"the quick brown fox\n" * 1000
        target.write_bytes(data)

        expected = hashlib.sha256(data).hexdigest()
        actual = runtime_signature.sha256_file(str(target))
        assert actual == expected
        assert actual.islower()


class TestPublicKeyResolution:
    def test_env_override_wins(self, monkeypatch, keypair_pem):
        _priv_pem, pub_pem = keypair_pem
        # Formato "\\n" encoded (como viaja en env vars de CI)
        inline = pub_pem.replace("\n", "\\n")
        monkeypatch.setenv("ORCH_RUNTIME_PUBLIC_KEY", inline)
        resolved = runtime_signature.get_runtime_public_key_pem()
        assert resolved == pub_pem

    def test_embedded_fallback_when_no_env(self, monkeypatch):
        monkeypatch.delenv("ORCH_RUNTIME_PUBLIC_KEY", raising=False)
        # En step 1 EMBEDDED_RUNTIME_PUBLIC_KEY está vacío; en step 2 debe tener
        # una clave válida generada en CI. El test sólo valida que la función
        # no crashea y retorna un string.
        resolved = runtime_signature.get_runtime_public_key_pem()
        assert isinstance(resolved, str)
