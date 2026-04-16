"""
Runtime Bootstrap — Lazy extraction + atomic swap
=================================================
Helper canónico para descomprimir el bundle del Core de forma perezosa:
sólo cuando el device realmente arranca server mode. Una APK / installer
ultra-liviana deja el tarball en ``assets_dir`` y esta rutina lo expande
bajo demanda.

Propiedades:

* **Idempotente**: boots sucesivos con la misma ``runtime_version`` no
  re-extraen. La marca es el archivo ``.extracted-version``.
* **Atómico**: extrae a ``<target>-extracting/`` y renombra a ``<target>/``
  al acabar. Si el proceso muere a mitad, la rutina detecta el directorio
  residual y lo limpia antes de reintentar.
* **Verifica integridad**: al terminar, recomputa SHA-256 del tarball y
  lo compara con el valor del manifest. Mismatch = rollback total.
* **Verifica firma**: si se provee clave pública, rechaza tarballs firmados
  con clave distinta.

El módulo Python es CANÓNICO — el launcher desktop lo invoca directamente;
Android tiene un mirror Kotlin en ``ShellEnvironment.kt`` que replica el
mismo flujo (tareas step 7 del plan).

Rev 0 — 2026-04-16 (plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tools.gimo_server.models.runtime import RuntimeCompression, RuntimeManifest
from tools.gimo_server.security.runtime_signature import (
    sha256_file,
    verify_manifest,
)

logger = logging.getLogger("orchestrator.runtime_bootstrap")


_EXTRACTED_MARKER = ".extracted-version"
_EXTRACTING_SUFFIX = "-extracting"
_PROBE_TIMEOUT_SECONDS = 5


class RuntimeBootstrapError(RuntimeError):
    """Error durante la extracción del bundle."""


@dataclass(frozen=True)
class BootstrapResult:
    """Información devuelta tras un intento de bootstrap."""

    runtime_dir: Path          # `<target>/` final, ya expandido
    python_binary: Path        # ruta al CPython dentro del bundle
    repo_root: Path            # raíz del repo dentro del bundle
    runtime_version: str       # versión extraída (para logs/telemetry)
    reused_existing: bool      # True si skipped por idempotencia


def _extraction_mode(compression: RuntimeCompression) -> str:
    if compression == RuntimeCompression.xz:
        return "r:xz"
    if compression == RuntimeCompression.none:
        return "r:"
    if compression == RuntimeCompression.zstd:
        raise RuntimeBootstrapError(
            "zstd extraction not implemented in bootstrap helper "
            "(MVP uses xz). Documented as follow-up in the plan."
        )
    raise RuntimeBootstrapError(f"unknown compression: {compression}")


def _read_manifest(assets_dir: Path) -> RuntimeManifest:
    manifest_path = assets_dir / "gimo-core-runtime.json"
    if not manifest_path.exists():
        raise RuntimeBootstrapError(
            f"manifest not found under assets_dir: {manifest_path}"
        )
    try:
        return RuntimeManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # schema fail, JSON fail, etc.
        raise RuntimeBootstrapError(f"invalid manifest JSON: {exc}") from exc


def _cleanup_residual(target_dir: Path) -> None:
    """Si hay un ``<target>-extracting/`` residual de un boot interrumpido, bórralo."""
    extracting = target_dir.with_name(target_dir.name + _EXTRACTING_SUFFIX)
    if extracting.exists():
        logger.warning("removing residual extracting dir: %s", extracting)
        shutil.rmtree(extracting, ignore_errors=True)


def _already_extracted(target_dir: Path, expected_version: str) -> bool:
    marker = target_dir / _EXTRACTED_MARKER
    if not marker.exists():
        return False
    actual = marker.read_text(encoding="utf-8").strip()
    return actual == expected_version


def _verify_tarball(tarball: Path, manifest: RuntimeManifest) -> None:
    actual = sha256_file(str(tarball))
    if actual != manifest.tarball_sha256:
        raise RuntimeBootstrapError(
            f"tarball sha256 mismatch for {tarball.name}: "
            f"expected={manifest.tarball_sha256} actual={actual}"
        )


def _extract_to_staging(tarball: Path, staging: Path, compression: RuntimeCompression) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, mode=_extraction_mode(compression)) as tf:
        # Python 3.12+ exige filter argument; usamos "data" para seguridad.
        try:
            tf.extractall(staging, filter="data")  # type: ignore[call-arg]
        except TypeError:
            # Fallback para Python 3.11 (sin filter arg)
            tf.extractall(staging)  # noqa: S202 (trusted bundle, signature-verified upstream)


def _probe_runtime_exec(python_binary: Path, target_value: str) -> None:
    """Ejecuta ``<python_binary> --version`` y detecta fallos de ABI temprano.

    BUGS_LATENTES §H8 fix (2026-04-17). El bootstrap original verificaba firma
    + sha + layout pero nunca intentaba EJECUTAR el binario. El E2E del S10
    del 2026-04-16 demostró que un bundle ``aarch64-unknown-linux-gnu`` es
    válido ELF + firma + sha + layout, pero Android Bionic rechaza el exec
    por TLS alignment mismatch (8 vs 64 bytes) — el fallo se manifestaba
    después del extract, como timeout silencioso en el runner.

    Este probe corta ese blind spot: si el binario no puede arrancar, el
    bootstrap falla aquí con un mensaje accionable en vez de dejar que el
    runner descubra el fallo 60s después.

    Casos detectados:
        * ``FileNotFoundError`` / ENOENT — binario inexistente o dynamic
          linker referenciado no disponible (cáso clásico Bionic vs glibc).
        * exit 126 — ``exec format error`` (ABI mismatch, TLS alignment, etc).
        * exit 127 — comando no encontrado (symlink roto, PATH mal).
        * ``subprocess.TimeoutExpired`` — el binario arranca pero cuelga.

    Raises:
        RuntimeBootstrapError con mensaje que incluye el target declarado
        en el manifest — facilita diagnosticar el mismatch host/target.
    """
    try:
        result = subprocess.run(
            [str(python_binary), "--version"],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeBootstrapError(
            f"python binary probe failed — file or dynamic linker not found "
            f"({exc.strerror or exc}). bundle target={target_value}; python={python_binary}. "
            f"common cause: ABI mismatch (e.g. aarch64-unknown-linux-gnu bundle "
            f"on Android Bionic — see docs/BUGS_LATENTES_20260416.md §H8)"
        ) from exc
    except PermissionError as exc:
        raise RuntimeBootstrapError(
            f"python binary probe failed — OS refused exec: {exc}. "
            f"bundle target={target_value}; python={python_binary}. "
            f"check that the bundle's python binary has execute permission"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeBootstrapError(
            f"python binary probe timed out after {_PROBE_TIMEOUT_SECONDS}s — "
            f"binary launches but hangs. bundle target={target_value}; "
            f"python={python_binary}. possibly missing shared libs or init deadlock"
        ) from exc
    except OSError as exc:
        raise RuntimeBootstrapError(
            f"python binary probe failed — OS rejected exec: {exc}. "
            f"bundle target={target_value}; python={python_binary}. "
            f"common cause: ABI mismatch between bundle target and host runtime"
        ) from exc

    if result.returncode != 0:
        stderr_tail = (result.stderr or b"")[-512:].decode("utf-8", errors="replace")
        raise RuntimeBootstrapError(
            f"python binary probe returned exit {result.returncode} "
            f"(target={target_value}, python={python_binary}). "
            f"exit 126 = exec format error (ABI mismatch); "
            f"exit 127 = linker cannot load binary. stderr tail: {stderr_tail!r}"
        )

    version_out = (result.stdout or result.stderr or b"").decode("utf-8", errors="replace").strip()
    logger.info(
        "runtime probe ok: python=%s target=%s reports %s",
        python_binary, target_value, version_out,
    )


def ensure_extracted(
    assets_dir: Path,
    target_dir: Path,
    *,
    public_key_pem: Optional[str] = None,
    allow_unsigned: bool = False,
    skip_exec_probe: bool = False,
) -> BootstrapResult:
    """Asegura que el bundle está descomprimido y listo para arrancar.

    Args:
        assets_dir: directorio con ``gimo-core-runtime.json`` + tarball firmado.
            En Android es ``<filesDir>/runtime-assets/`` tras copiar de ``assets/``;
            en desktop es el subdirectorio junto al launcher.
        target_dir: destino donde se expande el bundle (ej. ``<dataDir>/runtime/``).
            Si ya existe un bundle con la misma versión, se reusa.
        public_key_pem: clave pública Ed25519 a usar para verificar. ``None`` =
            usa la clave embebida / env var ``ORCH_RUNTIME_PUBLIC_KEY``.
        allow_unsigned: escape hatch SOLO para tests — rechaza verificación.
            Nunca usar en producción.
        skip_exec_probe: skip el probe `--version` del python binary. Default
            False (probe SIEMPRE en producción). Los tests con bundles
            sintéticos sin python real deben pasar ``True``. El probe detecta
            ABI mismatch / linker missing antes del primer uso del runtime.

    Returns:
        :class:`BootstrapResult` con las rutas absolutas relevantes.

    Raises:
        RuntimeBootstrapError: en cualquier fallo — manifest corrupto, firma
            inválida, tarball tampered, espacio insuficiente, probe de exec
            falla, etc.
    """
    assets_dir = Path(assets_dir).resolve()
    target_dir = Path(target_dir).resolve()

    manifest = _read_manifest(assets_dir)

    # Verificación de firma antes de tocar el filesystem destino
    if not allow_unsigned and not verify_manifest(manifest, public_key_pem):
        raise RuntimeBootstrapError(
            "runtime manifest signature verification failed — refusing to extract"
        )

    # Idempotencia: si ya está extraído en la versión correcta, skip.
    _cleanup_residual(target_dir)
    if _already_extracted(target_dir, manifest.runtime_version):
        logger.info(
            "runtime already extracted at %s (version=%s); skipping",
            target_dir, manifest.runtime_version,
        )
        python_binary = target_dir / manifest.python_rel_path
        repo_root = target_dir / manifest.repo_root_rel_path
        if python_binary.exists() and repo_root.exists():
            # BUGS_LATENTES §H8: probe pre-exec incluso en la rama idempotente
            # — un bundle que fue válido en un host puede ser inválido ahora
            # (ej. APK migrada a un device con ABI distinta sin re-extraer).
            if not skip_exec_probe:
                _probe_runtime_exec(python_binary, manifest.target.value)
            return BootstrapResult(
                runtime_dir=target_dir,
                python_binary=python_binary,
                repo_root=repo_root,
                runtime_version=manifest.runtime_version,
                reused_existing=True,
            )
        logger.warning("marker says extracted but files missing; re-extracting")

    tarball = assets_dir / manifest.tarball_name
    if not tarball.exists():
        raise RuntimeBootstrapError(f"tarball missing: {tarball}")
    _verify_tarball(tarball, manifest)

    # Extracción a staging + atomic swap
    staging = target_dir.with_name(target_dir.name + _EXTRACTING_SUFFIX)
    if staging.exists():
        shutil.rmtree(staging)
    _extract_to_staging(tarball, staging, manifest.compression)

    if target_dir.exists():
        # Guardamos el antiguo por si el swap falla (rollback simple)
        backup = target_dir.with_name(target_dir.name + "-backup")
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        target_dir.rename(backup)
        try:
            staging.rename(target_dir)
        except OSError:
            # swap falló — restauramos el backup
            backup.rename(target_dir)
            raise
        else:
            shutil.rmtree(backup, ignore_errors=True)
    else:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(target_dir)

    # Marcar extraído (se escribe DESPUÉS del rename — nunca queda stale)
    (target_dir / _EXTRACTED_MARKER).write_text(manifest.runtime_version, encoding="utf-8")

    python_binary = target_dir / manifest.python_rel_path
    repo_root = target_dir / manifest.repo_root_rel_path
    if not python_binary.exists() or not repo_root.exists():
        raise RuntimeBootstrapError(
            f"bundle layout invalid after extraction: "
            f"python={python_binary.exists()} repo={repo_root.exists()}"
        )

    # BUGS_LATENTES §H8: probe pre-exec antes de declarar el bootstrap OK.
    # Esto captura ABI mismatch, dynamic linker missing, permissos, etc. con
    # mensaje accionable — en vez de dejar que el runner descubra el fallo
    # después con un timeout silencioso.
    if not skip_exec_probe:
        _probe_runtime_exec(python_binary, manifest.target.value)

    logger.info(
        "runtime extracted: version=%s target=%s python=%s",
        manifest.runtime_version, manifest.target.value, python_binary,
    )
    return BootstrapResult(
        runtime_dir=target_dir,
        python_binary=python_binary,
        repo_root=repo_root,
        runtime_version=manifest.runtime_version,
        reused_existing=False,
    )
