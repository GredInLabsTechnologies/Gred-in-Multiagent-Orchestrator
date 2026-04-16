"""
GIMO Core Runtime Manifest — Canonical schema
==============================================
Describe un bundle del Core empaquetado (CPython + wheels + repo tree)
producido por ``scripts/package_core_runtime.py`` y consumido por:

- Android ``ShellEnvironment.prepareEmbeddedCoreRuntime()`` (via Kotlin mirror)
- Desktop launcher (``gimo.cmd`` / ``gimo.sh``)
- Runtime sync peer-to-peer (``/ops/mesh/runtime-manifest``)

El manifest se firma con Ed25519 (misma infraestructura que
``tools/gimo_server/security/license_guard.py``) — la firma cubre el hash
sha256 del tarball comprimido, no el manifest JSON en sí.

Rev 0 — 2026-04-16 (plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING)
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class RuntimeTarget(str, Enum):
    """Target hardware/OS tuples soportados.

    Los valores siguen la convención ``<os>-<arch>`` de python-build-standalone.
    La matriz MVP (2026-04-16) es ``android-arm64`` + ``windows-x86_64``; el resto
    se añaden cuando el CI tenga runners/recipes listos.
    """

    android_arm64 = "android-arm64"
    android_armv7 = "android-armv7"
    linux_x86_64 = "linux-x86_64"
    linux_arm64 = "linux-arm64"
    darwin_arm64 = "darwin-arm64"
    darwin_x86_64 = "darwin-x86_64"
    windows_x86_64 = "windows-x86_64"


class RuntimeCompression(str, Enum):
    """Algoritmo de compresión aplicado al tarball del bundle."""

    xz = "xz"
    zstd = "zstd"
    none = "none"


class RuntimeManifest(BaseModel):
    """Manifest canónico de un bundle del Core.

    Ejemplo de uso::

        manifest = RuntimeManifest(
            runtime_version="0.1.0",
            target=RuntimeTarget.android_arm64,
            compression=RuntimeCompression.xz,
            tarball_name="gimo-core-runtime.tar.xz",
            tarball_sha256="abc123...",
            compressed_size_bytes=13_500_000,
            uncompressed_size_bytes=47_200_000,
            python_rel_path="python/bin/python3.11",
            repo_root_rel_path="repo",
            python_path_entries=["repo", "site-packages"],
            files=["python/bin/python3.11", "site-packages/fastapi/__init__.py", ...],
            extra_env={"PYTHONDONTWRITEBYTECODE": "1"},
            signature="ed25519-hex",
        )

    El consumer Kotlin (Android) tiene un ``@Serializable`` espejo de este schema
    en ``EmbeddedCoreRuntimeManifest``. Los campos nuevos introducidos por este
    plan (``runtime_version``, ``target``, ``compression``, ``tarball_*``,
    ``*_size_bytes``, ``signature``) son opcionales en la lectura Kotlin para
    mantener backward compat con manifests antiguos que pudieran existir en
    instalaciones previas.
    """

    # Identificación del runtime --------------------------------------------
    runtime_version: str = Field(
        description="SemVer del bundle — incrementa con cada release del Core",
        min_length=1,
    )
    target: RuntimeTarget = Field(
        description="Target OS+arch del bundle (android-arm64, windows-x86_64, …)",
    )

    # Payload ---------------------------------------------------------------
    compression: RuntimeCompression = Field(
        default=RuntimeCompression.xz,
        description="Algoritmo de compresión del tarball",
    )
    tarball_name: str = Field(
        description="Nombre del archivo tarball (ej. gimo-core-runtime.tar.xz)",
        min_length=1,
    )
    tarball_sha256: str = Field(
        description="SHA-256 hex lowercase del tarball comprimido",
        pattern=r"^[0-9a-f]{64}$",
    )
    compressed_size_bytes: int = Field(
        ge=0,
        description="Tamaño en bytes del tarball comprimido",
    )
    uncompressed_size_bytes: int = Field(
        ge=0,
        description="Tamaño en bytes del tree expandido",
    )

    # Layout del tree expandido (rutas relativas al root de extracción) ------
    python_rel_path: str = Field(
        description="Ruta al binario CPython dentro del bundle expandido",
        min_length=1,
    )
    repo_root_rel_path: str = Field(
        description="Ruta al root del repo (donde vive tools/gimo_server)",
        min_length=1,
    )
    python_path_entries: List[str] = Field(
        default_factory=list,
        description="Rutas relativas que se inyectan en PYTHONPATH",
    )
    files: List[str] = Field(
        default_factory=list,
        description="Lista explícita de archivos del bundle (usado para validación)",
    )
    extra_env: Dict[str, str] = Field(
        default_factory=dict,
        description="Variables de entorno adicionales para el proceso del Core",
    )

    # Firma -----------------------------------------------------------------
    signature: str = Field(
        description=(
            "Firma Ed25519 hex lowercase sobre tarball_sha256 + target + runtime_version. "
            "Verificada con la clave pública bundled en runtime_signature.py."
        ),
        pattern=r"^[0-9a-f]{128}$",
    )

    # Campos opcionales informativos ----------------------------------------
    python_version: Optional[str] = Field(
        default=None,
        description="Versión de CPython bundled (informativo)",
    )
    built_at: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp del build",
    )
    builder: Optional[str] = Field(
        default=None,
        description="Identificación del productor (ej. CI job ID o 'local-dev')",
    )

    @field_validator("tarball_sha256", "signature", mode="before")
    @classmethod
    def _lowercase_hex(cls, v):
        """Normaliza hex a lowercase antes de aplicar el pattern regex.

        Ed25519 y SHA-256 son canónicos en lowercase; aceptamos uppercase en
        el input por conveniencia (algunos productores de hashes los emiten
        así) y normalizamos antes de validar.
        """
        if isinstance(v, str):
            return v.lower()
        return v

    @field_validator("python_rel_path", "repo_root_rel_path", "tarball_name")
    @classmethod
    def _no_absolute_paths(cls, v: str) -> str:
        """Las rutas del manifest son siempre relativas — nunca absolutas."""
        normalized = v.strip().lstrip("/")
        if ":" in normalized and len(normalized) > 2 and normalized[1] == ":":
            raise ValueError(f"path debe ser relativo, no absoluto Windows: {v!r}")
        return normalized

    def signing_payload(self) -> bytes:
        """Payload canónico sobre el que se computa la firma Ed25519.

        Formato estable: ``<tarball_sha256>|<target>|<runtime_version>``
        en UTF-8. Fácil de replicar en cualquier lenguaje (Python, Kotlin,
        Rust) sin ambigüedades de serialización JSON.
        """
        return f"{self.tarball_sha256}|{self.target.value}|{self.runtime_version}".encode("utf-8")
