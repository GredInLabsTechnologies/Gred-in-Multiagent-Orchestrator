"""Tests del productor ``scripts/package_core_runtime.py``.

Step 3 del plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING.

Los tests se centran en:
1. Detect-target no crashea y devuelve un valor válido del enum.
2. Build + verify end-to-end sobre target=host con un keypair efímero.
3. El manifest resultante es parseable y pasa verificación.

No ejercitan cross-compile (MVP usa CI para eso, step 9 del plan).

Marcado como ``slow_integration`` porque el build real tarda varios segundos
(instala wheels, copia stdlib, comprime). Los runners rápidos pueden skippear
con ``-m 'not slow_integration'`` — el conftest ya lo excluye por default.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
from tools.gimo_server.security.runtime_signature import verify_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "package_core_runtime.py"


def _run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Helper: corre el script y devuelve el CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )


@pytest.fixture
def ephemeral_keypair(tmp_path: Path) -> tuple[Path, Path]:
    """Genera un keypair Ed25519 efímero y lo escribe en PEM para el test."""
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_pem = priv.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    pub_pem = pub.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    )
    priv_path = tmp_path / "runtime_priv.pem"
    pub_path = tmp_path / "runtime_pub.pem"
    priv_path.write_bytes(priv_pem)
    pub_path.write_bytes(pub_pem)
    return priv_path, pub_path


class TestDetectTarget:
    def test_detect_target_outputs_known_value(self):
        result = _run("detect-target")
        assert result.returncode == 0, result.stderr
        out = result.stdout.strip()
        # Debe coincidir con algún valor del enum
        RuntimeTarget(out)


@pytest.mark.slow_integration
class TestBuildAndVerify:
    def test_build_host_bundle_e2e(self, tmp_path: Path, ephemeral_keypair):
        """Happy path: build de target host → manifest válido, firma verifica."""
        priv_path, pub_path = ephemeral_keypair
        output = tmp_path / "bundle"

        result = _run(
            "build",
            "--target", "host",
            "--output", str(output),
            "--runtime-version", "0.1.0-test",
            "--signing-key", str(priv_path),
            "--builder", "pytest-local",
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

        # Artefactos esperados
        manifest_path = output / "gimo-core-runtime.json"
        sig_path = output / "gimo-core-runtime.sig"
        tarball_candidates = list(output.glob("gimo-core-runtime.tar.*"))
        assert manifest_path.exists(), f"missing manifest in {list(output.iterdir())}"
        assert sig_path.exists()
        assert len(tarball_candidates) == 1, f"unexpected tarballs: {tarball_candidates}"
        tarball = tarball_candidates[0]
        assert tarball.stat().st_size > 0

        # Manifest parseable
        manifest = RuntimeManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        assert manifest.runtime_version == "0.1.0-test"
        assert manifest.builder == "pytest-local"
        assert manifest.compressed_size_bytes == tarball.stat().st_size
        assert manifest.uncompressed_size_bytes > manifest.compressed_size_bytes

        # Firma válida con la pub key pareada
        pub_pem = pub_path.read_text(encoding="utf-8")
        assert verify_manifest(manifest, pub_pem) is True

    def test_verify_cli_happy_path(self, tmp_path: Path, ephemeral_keypair):
        """El subcomando `verify` reporta OK sobre un bundle recién creado."""
        priv_path, pub_path = ephemeral_keypair
        output = tmp_path / "bundle"

        build_res = _run(
            "build",
            "--target", "host",
            "--output", str(output),
            "--runtime-version", "0.1.0-test",
            "--signing-key", str(priv_path),
        )
        assert build_res.returncode == 0, build_res.stderr

        verify_res = _run(
            "verify",
            "--bundle", str(output),
            "--public-key", str(pub_path),
        )
        assert verify_res.returncode == 0, verify_res.stderr
        assert "OK" in verify_res.stdout

    def test_verify_rejects_tampered_tarball(self, tmp_path: Path, ephemeral_keypair):
        """Alterar el tarball rompe la verificación (sha256 no coincide)."""
        priv_path, pub_path = ephemeral_keypair
        output = tmp_path / "bundle"

        _run(
            "build",
            "--target", "host",
            "--output", str(output),
            "--runtime-version", "0.1.0-test",
            "--signing-key", str(priv_path),
        )
        tarball = next(output.glob("gimo-core-runtime.tar.*"))

        # Flip un byte
        data = bytearray(tarball.read_bytes())
        data[-1] ^= 0x01
        tarball.write_bytes(bytes(data))

        verify_res = _run(
            "verify",
            "--bundle", str(output),
            "--public-key", str(pub_path),
        )
        assert verify_res.returncode != 0
        assert "sha256 mismatch" in verify_res.stderr.lower() or "sha256 mismatch" in verify_res.stdout.lower()

    def test_build_fails_without_signing_key(self, tmp_path: Path):
        """Sin clave privada, el build falla actionable — no silencioso."""
        output = tmp_path / "bundle"
        env = {"PATH": "", "ORCH_RUNTIME_SIGNING_KEY": ""}
        # Necesitamos el PATH para que pip funcione; usamos os.environ como base
        import os
        env = {**os.environ, "ORCH_RUNTIME_SIGNING_KEY": ""}

        result = _run(
            "build",
            "--target", "host",
            "--output", str(output),
            "--runtime-version", "0.1.0-test",
            env=env,
        )
        assert result.returncode != 0
        assert "signing key" in result.stderr.lower() or "signing key" in result.stdout.lower()

    def test_build_rejects_cross_compile_target(self, tmp_path: Path, ephemeral_keypair):
        """Un target que no coincide con el host falla actionable."""
        priv_path, _pub_path = ephemeral_keypair
        output = tmp_path / "bundle"

        # Pedimos android-arm64 desde un host x86_64/arm64 desktop — debe rechazar
        result = _run(
            "build",
            "--target", "android-arm64",
            "--output", str(output),
            "--runtime-version", "0.1.0-test",
            "--signing-key", str(priv_path),
        )
        assert result.returncode != 0
        combined = (result.stderr + result.stdout).lower()
        assert "cross" in combined or "ci matrix" in combined or "not available" in combined
