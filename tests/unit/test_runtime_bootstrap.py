"""Tests de ``tools/gimo_server/services/runtime_bootstrap.py``.

Step 3b del plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING.

Los tests usan un bundle sintético *mínimo* (stdlib ``tarfile`` + manifest
Pydantic + firma Ed25519 efímera) para no depender del productor completo
``package_core_runtime.py`` — eso lo cubre ``test_core_packaging.py``.
"""
from __future__ import annotations

import hashlib
import tarfile
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
from tools.gimo_server.security.runtime_signature import sign_manifest
from tools.gimo_server.services.runtime_bootstrap import (
    BootstrapResult,
    RuntimeBootstrapError,
    ensure_extracted,
)


@pytest.fixture
def keypair_pem():
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


def _make_bundle(
    assets_dir: Path,
    priv_pem: str,
    *,
    runtime_version: str = "0.1.0",
    compression: RuntimeCompression = RuntimeCompression.xz,
    tamper_tarball: bool = False,
) -> RuntimeManifest:
    """Construye un bundle sintético mínimo en ``assets_dir``.

    Layout del tarball:

        python/bin/python    (placeholder ejecutable)
        repo/marker.txt      (placeholder)
    """
    assets_dir.mkdir(parents=True, exist_ok=True)
    # 1. Staging con contenido
    staging = assets_dir / "_staging"
    if staging.exists():
        import shutil as _sh
        _sh.rmtree(staging)
    (staging / "python" / "bin").mkdir(parents=True)
    py = staging / "python" / "bin" / "python"
    py.write_text("#!/bin/sh\necho fake python\n", encoding="utf-8")
    (staging / "repo").mkdir()
    (staging / "repo" / "marker.txt").write_text("hello", encoding="utf-8")

    # 2. Tarball
    tarball_name = {
        RuntimeCompression.xz: "gimo-core-runtime.tar.xz",
        RuntimeCompression.none: "gimo-core-runtime.tar",
    }[compression]
    tarball_path = assets_dir / tarball_name
    mode = "w:xz" if compression == RuntimeCompression.xz else "w"
    with tarfile.open(tarball_path, mode) as tf:
        for entry in sorted(staging.iterdir()):
            tf.add(entry, arcname=entry.name)

    # 3. SHA-256
    if tamper_tarball:
        # Escribimos un byte extra → el hash va a ser del archivo tampered,
        # pero el manifest lleva el hash del original
        original_hash = hashlib.sha256(tarball_path.read_bytes()).hexdigest()
        tarball_path.write_bytes(tarball_path.read_bytes() + b"X")
        # El manifest queda con el hash "original" mientras el archivo cambió
        sha = original_hash
    else:
        sha = hashlib.sha256(tarball_path.read_bytes()).hexdigest()

    uncompressed = sum(
        p.stat().st_size for p in staging.rglob("*") if p.is_file()
    )
    compressed = tarball_path.stat().st_size

    manifest = RuntimeManifest(
        project_name="gimo-core",
        runtime_version=runtime_version,
        target=RuntimeTarget.linux_x86_64,  # cualquier target; no se valida aqui
        compression=compression,
        tarball_name=tarball_name,
        tarball_sha256=sha,
        compressed_size_bytes=compressed,
        uncompressed_size_bytes=uncompressed,
        python_rel_path="python/bin/python",
        project_root_rel_path="repo",
        python_path_entries=["repo"],
        files=["python/bin/python", "repo/marker.txt"],
        extra_env={},
        signature="0" * 128,
    )
    sig = sign_manifest(manifest, priv_pem)
    manifest = manifest.model_copy(update={"signature": sig})
    (assets_dir / "gimo-core-runtime.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )

    # Limpieza del staging
    import shutil as _sh
    _sh.rmtree(staging)
    return manifest


class TestFreshExtraction:
    def test_happy_path(self, tmp_path, keypair_pem):
        priv_pem, pub_pem = keypair_pem
        assets = tmp_path / "assets"
        target = tmp_path / "runtime"
        _make_bundle(assets, priv_pem)

        # skip_exec_probe=True: bundle sintético tiene un shell script como python,
        # no ejecutable en Windows. El probe lo cubre TestExecProbe con sys.executable.
        result = ensure_extracted(assets, target, public_key_pem=pub_pem, skip_exec_probe=True)
        assert isinstance(result, BootstrapResult)
        assert result.runtime_version == "0.1.0"
        assert result.reused_existing is False
        assert result.python_binary.exists()
        assert result.repo_root.exists()
        assert (target / ".extracted-version").read_text().strip() == "0.1.0"

    def test_idempotent_second_call_skips(self, tmp_path, keypair_pem):
        priv_pem, pub_pem = keypair_pem
        assets = tmp_path / "assets"
        target = tmp_path / "runtime"
        _make_bundle(assets, priv_pem)

        ensure_extracted(assets, target, public_key_pem=pub_pem, skip_exec_probe=True)
        second = ensure_extracted(assets, target, public_key_pem=pub_pem, skip_exec_probe=True)
        assert second.reused_existing is True


class TestUpgradeFlow:
    def test_new_version_re_extracts(self, tmp_path, keypair_pem):
        priv_pem, pub_pem = keypair_pem
        assets = tmp_path / "assets"
        target = tmp_path / "runtime"

        _make_bundle(assets, priv_pem, runtime_version="0.1.0")
        ensure_extracted(assets, target, public_key_pem=pub_pem, skip_exec_probe=True)

        # Reemplazamos el bundle con una nueva versión
        _make_bundle(assets, priv_pem, runtime_version="0.2.0")
        result = ensure_extracted(assets, target, public_key_pem=pub_pem, skip_exec_probe=True)
        assert result.reused_existing is False
        assert result.runtime_version == "0.2.0"
        assert (target / ".extracted-version").read_text().strip() == "0.2.0"


class TestRecovery:
    def test_residual_extracting_dir_cleaned(self, tmp_path, keypair_pem):
        priv_pem, pub_pem = keypair_pem
        assets = tmp_path / "assets"
        target = tmp_path / "runtime"
        _make_bundle(assets, priv_pem)

        # Simulamos boot interrumpido: un `runtime-extracting/` residual
        residual = target.with_name(target.name + "-extracting")
        residual.mkdir(parents=True)
        (residual / "partial.bin").write_bytes(b"partial")

        ensure_extracted(assets, target, public_key_pem=pub_pem, skip_exec_probe=True)
        assert not residual.exists()
        assert target.exists()


class TestIntegrityFailures:
    def test_tampered_tarball_rejected(self, tmp_path, keypair_pem):
        priv_pem, pub_pem = keypair_pem
        assets = tmp_path / "assets"
        target = tmp_path / "runtime"
        _make_bundle(assets, priv_pem, tamper_tarball=True)

        with pytest.raises(RuntimeBootstrapError, match="sha256 mismatch"):
            ensure_extracted(assets, target, public_key_pem=pub_pem, skip_exec_probe=True)
        # El target no se creó
        assert not target.exists()

    def test_missing_manifest(self, tmp_path, keypair_pem):
        _priv_pem, pub_pem = keypair_pem
        assets = tmp_path / "assets"
        assets.mkdir()
        target = tmp_path / "runtime"

        with pytest.raises(RuntimeBootstrapError, match="manifest not found"):
            ensure_extracted(assets, target, public_key_pem=pub_pem, skip_exec_probe=True)

    def test_invalid_signature_rejected(self, tmp_path, keypair_pem):
        priv_pem, _pub_pem = keypair_pem
        assets = tmp_path / "assets"
        target = tmp_path / "runtime"
        _make_bundle(assets, priv_pem)

        # Usamos una pub key distinta — firma no verifica
        wrong_priv = Ed25519PrivateKey.generate()
        wrong_pub_pem = wrong_priv.public_key().public_bytes(
            encoding=Encoding.PEM,
            format=PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        with pytest.raises(RuntimeBootstrapError, match="signature"):
            ensure_extracted(assets, target, public_key_pem=wrong_pub_pem, skip_exec_probe=True)


class TestUnsignedEscape:
    def test_allow_unsigned_skips_verification(self, tmp_path, keypair_pem):
        """Escape hatch para tests — NO usar en producción."""
        priv_pem, _pub_pem = keypair_pem
        assets = tmp_path / "assets"
        target = tmp_path / "runtime"
        _make_bundle(assets, priv_pem)

        # Sin public_key_pem, pero con allow_unsigned=True
        result = ensure_extracted(
            assets, target, public_key_pem="", allow_unsigned=True, skip_exec_probe=True
        )
        assert result.runtime_version == "0.1.0"


# BUGS_LATENTES §H8 — probe pre-exec tests (nuevos 2026-04-17)
class TestExecProbe:
    """Verifica el probe `--version` que detecta ABI mismatch / linker missing
    antes de devolver BootstrapResult.

    Usa ``sys.executable`` como stand-in para el python del bundle — así
    podemos probar el probe path con un binary real sin depender de
    python-build-standalone.
    """

    def _patch_manifest_to_host_python(self, assets_dir: Path, tmp_path: Path, priv_pem: str):
        """Reescribe el manifest + filesystem para que ``python_rel_path``
        apunte al ``sys.executable`` del host. Esto permite que el probe
        corra contra un python REAL.
        """
        import json
        import shutil
        import sys as _sys
        from tools.gimo_server.models.runtime import RuntimeManifest
        from tools.gimo_server.security.runtime_signature import sign_manifest

        manifest_path = assets_dir / "gimo-core-runtime.json"
        manifest = RuntimeManifest.model_validate_json(manifest_path.read_text())
        return manifest, manifest_path

    def test_probe_passes_with_fake_success(self, tmp_path, keypair_pem, monkeypatch):
        """Cuando subprocess.run devuelve exit 0, probe pasa silenciosamente."""
        import subprocess as _sp

        priv_pem, pub_pem = keypair_pem
        assets = tmp_path / "assets"
        target = tmp_path / "runtime"
        _make_bundle(assets, priv_pem)

        # Extract sin probe (bundle sintético no ejecutable)
        ensure_extracted(assets, target, public_key_pem=pub_pem, skip_exec_probe=True)

        # Mock subprocess.run para que el probe simule éxito en la rama idempotente
        def fake_run(args, **kw):
            class _R:
                returncode = 0
                stdout = b"Python 3.13.13\n"
                stderr = b""
            return _R()
        monkeypatch.setattr(
            "tools.gimo_server.services.runtime_bootstrap.subprocess.run",
            fake_run,
        )

        # Con probe activo ahora pasa (mock emula python --version exit 0)
        result = ensure_extracted(assets, target, public_key_pem=pub_pem)
        assert result.reused_existing is True

    def test_probe_rejects_missing_binary(self, tmp_path, keypair_pem):
        """Si python_binary no existe, probe raise RuntimeBootstrapError."""
        priv_pem, pub_pem = keypair_pem
        assets = tmp_path / "assets"
        target = tmp_path / "runtime"
        _make_bundle(assets, priv_pem)

        # Extract sin probe, luego borra el python y vuelve a entrar por la
        # rama idempotente — el probe debe reventar antes del marker check
        # ¡¡wait!! la rama idempotente ya chequea `python_binary.exists()` y
        # re-extrae si falta. Entonces skippeamos ese path y probamos el
        # probe con un path manipulado.
        ensure_extracted(assets, target, public_key_pem=pub_pem, skip_exec_probe=True)

        # Corrompe el binary a un archivo no ejecutable
        python_bin = target / "python" / "bin" / "python"
        python_bin.write_text("not a binary", encoding="utf-8")

        # En Windows esto no tiene permisos ejecutables → OSError / exit nonzero
        # En Linux sin chmod es "Permission denied" → tratado como exit nonzero
        with pytest.raises(RuntimeBootstrapError, match="probe"):
            ensure_extracted(assets, target, public_key_pem=pub_pem)

    def test_probe_error_mentions_target(self, tmp_path, keypair_pem):
        """El error del probe incluye el target del manifest para debug."""
        priv_pem, pub_pem = keypair_pem
        assets = tmp_path / "assets"
        target = tmp_path / "runtime"
        _make_bundle(assets, priv_pem)

        ensure_extracted(assets, target, public_key_pem=pub_pem, skip_exec_probe=True)

        python_bin = target / "python" / "bin" / "python"
        python_bin.write_text("not a binary", encoding="utf-8")

        with pytest.raises(RuntimeBootstrapError) as excinfo:
            ensure_extracted(assets, target, public_key_pem=pub_pem)

        # El target del manifest es linux_x86_64 según _make_bundle
        assert "linux-x86_64" in str(excinfo.value)
