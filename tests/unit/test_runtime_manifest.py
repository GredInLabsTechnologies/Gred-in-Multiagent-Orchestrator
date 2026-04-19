"""Tests del schema canónico ``RuntimeManifest``.

Step 1 del plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING — tests
contractuales sobre el schema Pydantic. NO prueban firma (eso vive en
``test_runtime_signature.py``); sólo validan que el contrato está bien
definido y es robusto a inputs hostiles.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from tools.gimo_server.models.runtime import (
    RuntimeCompression,
    RuntimeManifest,
    RuntimeTarget,
)


SHA_VALID = "a" * 64
SIG_VALID = "b" * 128


def _base_manifest(**overrides):
    """Factory con defaults válidos — los tests sólo overriden lo que prueban."""
    fields = dict(
        project_name="gimo-core",
        runtime_version="0.1.0",
        target=RuntimeTarget.android_arm64,
        compression=RuntimeCompression.xz,
        tarball_name="gimo-core-runtime.tar.xz",
        tarball_sha256=SHA_VALID,
        compressed_size_bytes=13_500_000,
        uncompressed_size_bytes=47_200_000,
        python_rel_path="python/bin/python3.11",
        project_root_rel_path="repo",
        python_path_entries=["repo", "site-packages"],
        files=["python/bin/python3.11", "site-packages/fastapi/__init__.py"],
        extra_env={"PYTHONDONTWRITEBYTECODE": "1"},
        signature=SIG_VALID,
    )
    fields.update(overrides)
    return RuntimeManifest(**fields)


class TestRuntimeManifestRoundTrip:
    def test_round_trip_json(self):
        original = _base_manifest()
        as_json = original.model_dump_json()
        parsed = RuntimeManifest.model_validate_json(as_json)
        assert parsed == original

    def test_defaults_sensible(self):
        # `compression` default es xz (el más eficiente para tree CPython+stdlib)
        m = _base_manifest()
        assert m.compression == RuntimeCompression.xz
        # campos opcionales por default son None / vacíos
        assert m.python_version is None
        assert m.built_at is None
        assert m.builder is None


class TestRuntimeManifestTargets:
    @pytest.mark.parametrize(
        "target",
        [
            RuntimeTarget.android_arm64,
            RuntimeTarget.android_armv7,
            RuntimeTarget.linux_x86_64,
            RuntimeTarget.linux_arm64,
            RuntimeTarget.darwin_arm64,
            RuntimeTarget.darwin_x86_64,
            RuntimeTarget.windows_x86_64,
        ],
    )
    def test_all_targets_valid(self, target):
        m = _base_manifest(target=target)
        assert m.target == target

    def test_invalid_target_rejected(self):
        with pytest.raises(ValidationError):
            _base_manifest(target="freebsd-riscv")  # type: ignore[arg-type]


class TestRuntimeManifestCompression:
    @pytest.mark.parametrize(
        "compression",
        [RuntimeCompression.xz, RuntimeCompression.zstd, RuntimeCompression.none],
    )
    def test_all_compressions_valid(self, compression):
        m = _base_manifest(compression=compression)
        assert m.compression == compression

    def test_invalid_compression_rejected(self):
        with pytest.raises(ValidationError):
            _base_manifest(compression="brotli")  # type: ignore[arg-type]


class TestRuntimeManifestHashAndSignatureFormat:
    def test_sha256_must_be_64_hex(self):
        with pytest.raises(ValidationError):
            _base_manifest(tarball_sha256="short")
        with pytest.raises(ValidationError):
            _base_manifest(tarball_sha256="z" * 64)  # 'z' no es hex

    def test_signature_must_be_128_hex(self):
        with pytest.raises(ValidationError):
            _base_manifest(signature="short")
        with pytest.raises(ValidationError):
            _base_manifest(signature="z" * 128)  # 'z' no es hex

    def test_hashes_normalized_to_lowercase(self):
        upper = _base_manifest(
            tarball_sha256="A" * 64,
            signature="B" * 128,
        )
        assert upper.tarball_sha256 == "a" * 64
        assert upper.signature == "b" * 128


class TestRuntimeManifestPaths:
    def test_relative_paths_accepted(self):
        m = _base_manifest(
            python_rel_path="python/bin/python3.11",
            project_root_rel_path="repo",
        )
        assert m.python_rel_path == "python/bin/python3.11"
        assert m.project_root_rel_path == "repo"

    def test_leading_slash_stripped(self):
        m = _base_manifest(python_rel_path="/python/bin/python3.11")
        assert m.python_rel_path == "python/bin/python3.11"

    def test_absolute_windows_path_rejected(self):
        with pytest.raises(ValidationError):
            _base_manifest(python_rel_path="C:\\python\\python.exe")


class TestRuntimeManifestSigningPayload:
    def test_signing_payload_is_stable(self):
        """El payload firmable es determinista y lenguaje-agnóstico.

        Rove 1.0.0 añadió ``project_name`` como cuarto componente para
        prevenir cross-project confusion attacks (mismo sha+target+version
        re-etiquetado como otro proyecto). Formato canónico:
        ``<sha256>|<target>|<runtime_version>|<project_name>``.
        """
        m = _base_manifest(
            project_name="gimo-core",
            tarball_sha256="c" * 64,
            target=RuntimeTarget.android_arm64,
            runtime_version="1.2.3",
        )
        payload = m.signing_payload()
        expected = (
            b"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
            b"|android-arm64|1.2.3|gimo-core"
        )
        assert payload == expected

    def test_signing_payload_changes_with_fields(self):
        """Cambiar cualquier campo firmado altera el payload."""
        base = _base_manifest(
            tarball_sha256="1" * 64,
            target=RuntimeTarget.android_arm64,
            runtime_version="1.0.0",
            project_name="gimo-core",
        )
        diff_hash = base.model_copy(update={"tarball_sha256": "2" * 64})
        diff_target = base.model_copy(update={"target": RuntimeTarget.windows_x86_64})
        diff_version = base.model_copy(update={"runtime_version": "1.0.1"})
        diff_project = base.model_copy(update={"project_name": "other-project"})

        payloads = {
            base.signing_payload(),
            diff_hash.signing_payload(),
            diff_target.signing_payload(),
            diff_version.signing_payload(),
            diff_project.signing_payload(),
        }
        # 5 distintos — ningún par colisiona (project_name rompe cross-project confusion)
        assert len(payloads) == 5


class TestRuntimeManifestSizeSanity:
    def test_negative_sizes_rejected(self):
        with pytest.raises(ValidationError):
            _base_manifest(compressed_size_bytes=-1)
        with pytest.raises(ValidationError):
            _base_manifest(uncompressed_size_bytes=-1)

    def test_zero_sizes_allowed(self):
        # Edge case: bundle vacío (degenerate) técnicamente válido en schema;
        # la validación semántica ("compressed debe ser < uncompressed") se hace
        # en el productor (package_core_runtime.py), no en el schema.
        m = _base_manifest(compressed_size_bytes=0, uncompressed_size_bytes=0)
        assert m.compressed_size_bytes == 0
