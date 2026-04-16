"""Tests del router ``/ops/mesh/runtime-manifest`` y ``/ops/mesh/runtime-payload``.

Step 4 del plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING (Change 4).

Contratos cubiertos:

* Sin auth → 401.
* Con auth + sin bundle → 404 con mensaje actionable.
* Con bundle sintético → 200 + manifest/payload válido.
* ``Range`` header → 206 + primer chunk correcto.
* Rate limit estricto para ``runtime-payload`` (bucket separado del rol).
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


def _make_bundle(assets_dir: Path) -> tuple[RuntimeManifest, str]:
    """Construye un bundle sintético mínimo — reusa el patrón del test_runtime_bootstrap."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    staging = assets_dir / "_staging"
    if staging.exists():
        import shutil as _sh
        _sh.rmtree(staging)
    (staging / "python" / "bin").mkdir(parents=True)
    (staging / "python" / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    (staging / "repo").mkdir()
    (staging / "repo" / "marker.txt").write_text("hello", encoding="utf-8")

    tarball_path = assets_dir / "gimo-core-runtime.tar.xz"
    with tarfile.open(tarball_path, "w:xz") as tf:
        for entry in sorted(staging.iterdir()):
            tf.add(entry, arcname=entry.name)

    sha = hashlib.sha256(tarball_path.read_bytes()).hexdigest()
    uncompressed = sum(p.stat().st_size for p in staging.rglob("*") if p.is_file())
    compressed = tarball_path.stat().st_size

    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    manifest = RuntimeManifest(
        runtime_version="0.1.0-endpoint-test",
        target=RuntimeTarget.linux_x86_64,
        compression=RuntimeCompression.xz,
        tarball_name="gimo-core-runtime.tar.xz",
        tarball_sha256=sha,
        compressed_size_bytes=compressed,
        uncompressed_size_bytes=uncompressed,
        python_rel_path="python/bin/python",
        repo_root_rel_path="repo",
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
    import shutil as _sh
    _sh.rmtree(staging)
    return manifest, pub_pem


@pytest.fixture
def runtime_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Crea un bundle sintético y expone el directorio vía ORCH_RUNTIME_ASSETS_DIR."""
    assets = tmp_path / "runtime-assets"
    manifest, pub_pem = _make_bundle(assets)
    monkeypatch.setenv("ORCH_RUNTIME_ASSETS_DIR", str(assets))
    yield {"assets": assets, "manifest": manifest, "pub_pem": pub_pem}


@pytest.fixture
def _clear_rate_limit():
    """Limpia los buckets de rate limit para tests aislados."""
    from tools.gimo_server.security.rate_limit import rate_limit_store
    rate_limit_store.clear()
    yield
    rate_limit_store.clear()


class TestRuntimeManifestEndpoint:
    def test_requires_auth(self, test_client):
        r = test_client.get("/ops/mesh/runtime-manifest")
        assert r.status_code == 401

    def test_returns_404_without_bundle(self, test_client, valid_token, tmp_path, monkeypatch, _clear_rate_limit):
        # Apuntar a un dir vacío
        empty = tmp_path / "no-bundle"
        empty.mkdir()
        monkeypatch.setenv("ORCH_RUNTIME_ASSETS_DIR", str(empty))
        r = test_client.get(
            "/ops/mesh/runtime-manifest",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert r.status_code == 404
        assert "manifest" in r.json()["detail"].lower()

    def test_returns_manifest(self, test_client, valid_token, runtime_assets, _clear_rate_limit):
        r = test_client.get(
            "/ops/mesh/runtime-manifest",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["runtime_version"] == "0.1.0-endpoint-test"
        assert body["target"] == "linux-x86_64"
        assert body["compression"] == "xz"
        assert len(body["tarball_sha256"]) == 64
        assert len(body["signature"]) == 128


class TestRuntimePayloadEndpoint:
    def test_requires_auth(self, test_client):
        r = test_client.get("/ops/mesh/runtime-payload")
        assert r.status_code == 401

    def test_full_download(self, test_client, valid_token, runtime_assets, _clear_rate_limit):
        r = test_client.get(
            "/ops/mesh/runtime-payload",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert r.status_code == 200, r.text
        # Sha256 del body debe coincidir con el manifest
        expected_sha = runtime_assets["manifest"].tarball_sha256
        actual_sha = hashlib.sha256(r.content).hexdigest()
        assert actual_sha == expected_sha
        assert r.headers.get("x-runtime-version") == "0.1.0-endpoint-test"
        assert r.headers.get("x-runtime-sha256") == expected_sha

    def test_range_request_returns_206(self, test_client, valid_token, runtime_assets, _clear_rate_limit):
        r = test_client.get(
            "/ops/mesh/runtime-payload",
            headers={
                "Authorization": f"Bearer {valid_token}",
                "Range": "bytes=0-63",
            },
        )
        assert r.status_code == 206
        assert len(r.content) == 64
        assert r.headers["content-range"].startswith("bytes 0-63/")
        assert r.headers["content-length"] == "64"

    def test_invalid_range_returns_416(self, test_client, valid_token, runtime_assets, _clear_rate_limit):
        r = test_client.get(
            "/ops/mesh/runtime-payload",
            headers={
                "Authorization": f"Bearer {valid_token}",
                "Range": "bytes=999999999-999999999",
            },
        )
        assert r.status_code == 416

    def test_strict_rate_limit(self, test_client, valid_token, runtime_assets, _clear_rate_limit):
        """7ª request en < 60s desde la misma IP → 429."""
        headers = {"Authorization": f"Bearer {valid_token}"}
        # Las 6 primeras pasan (limit=6)
        for _ in range(6):
            r = test_client.get("/ops/mesh/runtime-payload", headers=headers)
            assert r.status_code == 200
        # La 7ª es rechazada
        r = test_client.get("/ops/mesh/runtime-payload", headers=headers)
        assert r.status_code == 429
        assert "too many" in r.json()["detail"].lower()
