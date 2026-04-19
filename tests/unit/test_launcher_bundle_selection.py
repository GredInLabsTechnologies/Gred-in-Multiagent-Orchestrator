"""Tests del selector de intérprete en ``gimo_cli.commands.server._resolve_launcher_python``.

Step 6 del plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING (Change 6).

La decisión es tres líneas de lógica, pero define el contrato:

* Sin bundle → host Python (sys.executable), provenance "host".
* Con bundle válido (+ escape hatch allow_unsigned) → bundle Python, provenance "bundle".
* Con bundle corrupto → fallback a host con warning (no crash).

Reusa el patrón sintético de ``tests/unit/test_runtime_bootstrap.py``.
"""
from __future__ import annotations

import hashlib
import sys
import tarfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from tools.gimo_server.models.runtime import (
    RuntimeCompression,
    RuntimeManifest,
    RuntimeTarget,
)
from tools.gimo_server.security.runtime_signature import sign_manifest


def _make_bundle(assets_dir: Path, priv_pem: str) -> None:
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
    manifest = RuntimeManifest(
        project_name="gimo-core",
        runtime_version="0.1.0-launcher",
        target=RuntimeTarget.linux_x86_64,
        compression=RuntimeCompression.xz,
        tarball_name="gimo-core-runtime.tar.xz",
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
    import shutil as _sh
    _sh.rmtree(staging)


@pytest.fixture
def keypair_pem():
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode("utf-8")
    return priv_pem


def test_no_bundle_returns_host(tmp_path):
    from gimo_cli.commands.server import _resolve_launcher_python
    env = {}
    python_exe, pythonpath_extra, provenance = _resolve_launcher_python(tmp_path, env)
    assert python_exe == sys.executable
    assert pythonpath_extra is None
    assert provenance == "host"


def test_bundle_with_allow_unsigned_returns_bundle(tmp_path, keypair_pem):
    assets = tmp_path / "runtime-assets"
    _make_bundle(assets, keypair_pem)
    env = {
        "ORCH_RUNTIME_ASSETS_DIR": str(assets),
        "ORCH_RUNTIME_DIR": str(tmp_path / "runtime"),
        "ORCH_RUNTIME_ALLOW_UNSIGNED": "1",
        # BUGS_LATENTES §H8: bundle sintético no ejecutable en Windows/Mac;
        # skip probe para que provenance="bundle". En producción sin este env
        # el probe atrapa ABI mismatch y hace fallback correcto a "host".
        "ORCH_RUNTIME_SKIP_EXEC_PROBE": "1",
    }
    from gimo_cli.commands.server import _resolve_launcher_python
    python_exe, pythonpath_extra, provenance = _resolve_launcher_python(tmp_path, env)
    assert provenance == "bundle"
    assert Path(python_exe).exists()
    assert pythonpath_extra is not None
    assert Path(pythonpath_extra).is_dir()


def test_bundle_missing_tarball_falls_back_to_host(tmp_path, keypair_pem):
    """Si el bundle está presente pero corrupto → fallback a host, no crash."""
    assets = tmp_path / "runtime-assets"
    _make_bundle(assets, keypair_pem)
    # Corrompemos borrando el tarball pero dejando el manifest → bootstrap falla
    (assets / "gimo-core-runtime.tar.xz").unlink()
    env = {
        "ORCH_RUNTIME_ASSETS_DIR": str(assets),
        "ORCH_RUNTIME_DIR": str(tmp_path / "runtime"),
        "ORCH_RUNTIME_ALLOW_UNSIGNED": "1",
    }
    from gimo_cli.commands.server import _resolve_launcher_python
    python_exe, pythonpath_extra, provenance = _resolve_launcher_python(tmp_path, env)
    assert provenance == "host"
    assert python_exe == sys.executable
    assert pythonpath_extra is None
