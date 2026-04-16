"""Tests del servicio ``runtime_upgrader.upgrade_from_peer``.

Step 8 del plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING.

Estrategia:

* No arrancamos un servidor HTTP real. Monkey-patcheamos ``urllib.request.urlopen``
  para devolver respuestas sintéticas que imitan ``/ops/mesh/runtime-manifest``
  y ``/ops/mesh/runtime-payload``.
* Generamos un bundle válido con ``_make_bundle`` (mismo patrón que
  ``test_launcher_bundle_selection.py``) y lo servimos como payload.
* Cubrimos: up-to-date, upgrade, sha mismatch (sabotaje intencional),
  firma inválida, downgrade (requiere flag).
"""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Optional
from unittest.mock import patch

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
from tools.gimo_server.services.runtime_upgrader import (
    RuntimeUpgradeError,
    UpgradeOutcome,
    upgrade_from_peer,
)


# ── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture
def keypair():
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


def _build_bundle(version: str, priv_pem: str, *, staging_marker: str = "hello") -> tuple[bytes, RuntimeManifest]:
    """Construye bundle in-memory y devuelve ``(tarball_bytes, manifest)``."""
    # Staging virtual en memoria vía tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        # python binary
        py_data = b"#!/bin/sh\n"
        info = tarfile.TarInfo("python/bin/python")
        info.size = len(py_data)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(py_data))
        # repo marker
        repo_data = staging_marker.encode("utf-8")
        info = tarfile.TarInfo("repo/marker.txt")
        info.size = len(repo_data)
        tf.addfile(info, io.BytesIO(repo_data))
    tarball_bytes = buf.getvalue()
    sha = hashlib.sha256(tarball_bytes).hexdigest()

    manifest = RuntimeManifest(
        runtime_version=version,
        target=RuntimeTarget.linux_x86_64,
        compression=RuntimeCompression.xz,
        tarball_name="gimo-core-runtime.tar.xz",
        tarball_sha256=sha,
        compressed_size_bytes=len(tarball_bytes),
        uncompressed_size_bytes=len(b"#!/bin/sh\n") + len(staging_marker.encode()),
        python_rel_path="python/bin/python",
        repo_root_rel_path="repo",
        python_path_entries=["repo"],
        files=["python/bin/python", "repo/marker.txt"],
        extra_env={},
        signature="0" * 128,
    )
    sig = sign_manifest(manifest, priv_pem)
    manifest = manifest.model_copy(update={"signature": sig})
    return tarball_bytes, manifest


class FakeResponse:
    """Emula el objeto context-manager retornado por urlopen."""

    def __init__(self, body: bytes, status: int = 200, headers: Optional[dict] = None):
        self._body = body
        self._status = status
        self._headers = headers or {}
        self._pos = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return self._status

    @property
    def headers(self):
        # simula mapping case-sensitive get()
        class _H:
            def __init__(self, d): self._d = d
            def get(self, k, default=None):
                for key, v in self._d.items():
                    if key.lower() == k.lower():
                        return v
                return default
        return _H(self._headers)

    def read(self, n: int = -1):
        if n < 0:
            out = self._body[self._pos:]
            self._pos = len(self._body)
            return out
        out = self._body[self._pos : self._pos + n]
        self._pos += len(out)
        return out


def _make_urlopen(manifest: RuntimeManifest, tarball: bytes):
    """Crea un fake urlopen que responde a /runtime-manifest y /runtime-payload."""

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        if "/runtime-manifest" in url:
            body = manifest.model_dump_json().encode("utf-8")
            return FakeResponse(body, status=200, headers={"Content-Type": "application/json"})
        if "/runtime-payload" in url:
            # Respetamos Range si viene
            range_h = req.headers.get("Range")
            if range_h and range_h.startswith("bytes="):
                start = int(range_h.split("=", 1)[1].split("-")[0])
                body = tarball[start:]
                headers = {
                    "Content-Range": f"bytes {start}-{len(tarball)-1}/{len(tarball)}",
                    "Content-Length": str(len(body)),
                }
                return FakeResponse(body, status=206, headers=headers)
            return FakeResponse(
                tarball,
                status=200,
                headers={"Content-Length": str(len(tarball))},
            )
        raise AssertionError(f"unexpected URL: {url}")

    return fake_urlopen


# ── Tests ────────────────────────────────────────────────────────────────────
def test_upgrade_from_empty_local_downloads_and_extracts(tmp_path, keypair):
    priv, pub = keypair
    tarball, manifest = _build_bundle("0.2.0", priv)
    assets = tmp_path / "assets"
    target = tmp_path / "runtime"

    with patch("urllib.request.urlopen", side_effect=_make_urlopen(manifest, tarball)):
        result = upgrade_from_peer(
            "http://peer:9325",
            assets_dir=assets,
            target_dir=target,
            token="t",
            public_key_pem=pub,
            skip_exec_probe=True,  # bundle sintético sin python real
        )

    assert result.outcome == UpgradeOutcome.UPGRADED
    assert result.from_version is None
    assert result.to_version == "0.2.0"
    assert result.bytes_transferred == len(tarball)
    assert result.bootstrap is not None
    assert result.bootstrap.python_binary.exists()
    assert result.bootstrap.repo_root.is_dir()
    # Archivos promovidos
    assert (assets / "gimo-core-runtime.json").exists()
    assert (assets / "gimo-core-runtime.tar.xz").exists()
    assert (assets / "gimo-core-runtime.sig").exists()


def test_upgrade_same_version_is_noop(tmp_path, keypair):
    priv, pub = keypair
    tarball, manifest = _build_bundle("0.2.0", priv)
    assets = tmp_path / "assets"
    target = tmp_path / "runtime"
    assets.mkdir(parents=True)
    # Pre-sembramos el manifest local con la misma versión
    (assets / "gimo-core-runtime.json").write_text(manifest.model_dump_json(), encoding="utf-8")

    with patch("urllib.request.urlopen", side_effect=_make_urlopen(manifest, tarball)):
        result = upgrade_from_peer(
            "http://peer:9325",
            assets_dir=assets,
            target_dir=target,
            token="t",
            public_key_pem=pub,
        )

    assert result.outcome == UpgradeOutcome.UP_TO_DATE
    assert result.from_version == "0.2.0"
    assert result.to_version == "0.2.0"
    assert result.bytes_transferred == 0
    assert not target.exists()  # no-op no crea nada


def test_upgrade_rejects_downgrade_without_flag(tmp_path, keypair):
    priv, pub = keypair
    # Local = 0.3.0, remote = 0.2.0 — más viejo.
    _old_tarball, old_manifest = _build_bundle("0.2.0", priv)
    assets = tmp_path / "assets"
    target = tmp_path / "runtime"
    assets.mkdir(parents=True)
    # local 0.3.0
    _new_tarball, new_manifest = _build_bundle("0.3.0", priv)
    (assets / "gimo-core-runtime.json").write_text(
        new_manifest.model_dump_json(), encoding="utf-8"
    )

    with patch("urllib.request.urlopen", side_effect=_make_urlopen(old_manifest, _old_tarball)):
        with pytest.raises(RuntimeUpgradeError, match="older than local"):
            upgrade_from_peer(
                "http://peer:9325",
                assets_dir=assets,
                target_dir=target,
                token="t",
                public_key_pem=pub,
            )


def test_upgrade_sha_mismatch_aborts_and_cleans(tmp_path, keypair):
    priv, pub = keypair
    tarball, manifest = _build_bundle("0.2.0", priv)
    # Saboteamos el manifest: le ponemos un sha256 equivocado (y re-firmamos)
    bad_manifest = manifest.model_copy(update={
        "tarball_sha256": "0" * 64,
        "signature": "0" * 128,
    })
    bad_sig = sign_manifest(bad_manifest, priv)
    bad_manifest = bad_manifest.model_copy(update={"signature": bad_sig})

    assets = tmp_path / "assets"
    target = tmp_path / "runtime"

    with patch("urllib.request.urlopen", side_effect=_make_urlopen(bad_manifest, tarball)):
        with pytest.raises(RuntimeUpgradeError, match="sha256 mismatch"):
            upgrade_from_peer(
                "http://peer:9325",
                assets_dir=assets,
                target_dir=target,
                token="t",
                public_key_pem=pub,
            )
    # El partial debe estar limpio
    partial = assets / "gimo-core-runtime.tar.xz.download-partial"
    assert not partial.exists(), "partial no se limpió tras fallo de sha"


def test_upgrade_invalid_signature_is_rejected(tmp_path, keypair):
    priv, _pub = keypair
    # Construimos con priv, pero verificaremos con otra clave pública
    other_priv = Ed25519PrivateKey.generate()
    other_pub = other_priv.public_key().public_bytes(
        encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    tarball, manifest = _build_bundle("0.2.0", priv)
    assets = tmp_path / "assets"
    target = tmp_path / "runtime"

    with patch("urllib.request.urlopen", side_effect=_make_urlopen(manifest, tarball)):
        with pytest.raises(RuntimeUpgradeError, match="signature verification failed"):
            upgrade_from_peer(
                "http://peer:9325",
                assets_dir=assets,
                target_dir=target,
                token="t",
                public_key_pem=other_pub,
            )


def test_upgrade_peer_url_normalization(tmp_path, keypair):
    priv, pub = keypair
    tarball, manifest = _build_bundle("0.2.0", priv)
    assets = tmp_path / "assets"
    target = tmp_path / "runtime"

    # URL con trailing slash y path extra → debe normalizar a base
    captured_urls: list[str] = []

    def capturing_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        captured_urls.append(url)
        return _make_urlopen(manifest, tarball)(req, timeout=timeout)

    with patch("urllib.request.urlopen", side_effect=capturing_urlopen):
        upgrade_from_peer(
            "http://peer:9325/some/trailing/path",
            assets_dir=assets,
            target_dir=target,
            token="t",
            public_key_pem=pub,
            skip_exec_probe=True,  # bundle sintético sin python real
        )

    # Las URLs emitidas deben ser http://peer:9325/ops/mesh/runtime-*
    assert any(u == "http://peer:9325/ops/mesh/runtime-manifest" for u in captured_urls)
    assert any(u == "http://peer:9325/ops/mesh/runtime-payload" for u in captured_urls)


def test_upgrade_rejects_empty_peer_url(tmp_path):
    with pytest.raises(RuntimeUpgradeError, match="peer_url"):
        upgrade_from_peer(
            "",
            assets_dir=tmp_path / "a",
            target_dir=tmp_path / "t",
        )
