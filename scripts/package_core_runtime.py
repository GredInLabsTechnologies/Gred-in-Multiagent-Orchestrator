#!/usr/bin/env python3
"""
GIMO Core Runtime Packager
==========================
Produce un bundle autocontenido, comprimido y firmado del Core GIMO para
ser consumido por Android (``ShellEnvironment.prepareEmbeddedCoreRuntime``),
por el desktop launcher o por el endpoint de upgrade peer-to-peer.

Subcomandos:

    detect-target          Imprime el target (``<os>-<arch>``) actual
    build                  Produce un bundle firmado para un target
    verify                 Valida firma + sha256 de un bundle existente

Target `host` (default) empaqueta el Python del sistema donde corre el
script (útil para develop + tests locales). Los targets cross-platform
(android-arm64, windows-x86_64, etc.) requieren python-build-standalone
y wheels pre-compilados — se integran en el CI matrix (step 9 del plan).

Rev 0 — 2026-04-16 (plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import urllib.request
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# El script corre desde el repo root; añadir al path para imports relativos
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.gimo_server.models.runtime import (  # noqa: E402
    RuntimeCompression,
    RuntimeManifest,
    RuntimeTarget,
)
from tools.gimo_server.security.runtime_signature import (  # noqa: E402
    RuntimeSignatureError,
    sha256_file,
    sign_manifest,
)

logger = logging.getLogger("package_core_runtime")
logging.basicConfig(
    level=os.environ.get("PACKAGER_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)


# --------------------------------------------------------------------- consts
_TARBALL_NAME = "gimo-core-runtime.tar"
_MANIFEST_NAME = "gimo-core-runtime.json"
_SIG_NAME = "gimo-core-runtime.sig"

# Subdirectorios del repo que el Core necesita en runtime.
# Cerrado y acotado — si aparece una dep nueva crítica se añade aquí
# explícitamente (no wildcards que arrastren basura).
_REPO_INCLUDES = [
    "tools/gimo_server",
    "tools/mcp_bridge",
    "tools/orchestrator_cli",
    "gimo_cli",
    "gimo.py",
    "data",
    "docs/SECURITY.md",  # referenced by license_guard
]

_REQUIREMENTS_FILE = "requirements.txt"

# --------------------------------------------------------------------- cross-compile
#
# Plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_CROSS_COMPILE:
#   Change 1 — fetcher python-build-standalone
#   Change 2 — pip install --platform
#
# Con `--python-source=standalone` el productor descarga un CPython pre-construido
# de astral-sh/python-build-standalone (publicado bajo GitHub releases). Esto
# desbloquea bundles reales cross-platform (android-arm64, darwin-arm64, …) sin
# depender del Python host del CI runner.
#
# Las wheels de las deps se resuelven con `pip install --platform <tag>
# --only-binary=:all:`, que descarga wheels pre-compiladas desde PyPI y aborta
# duro si una dep no publica wheel compatible con el target — previene
# cross-compile silenciosamente roto.

# Versión pineada de python-build-standalone. Subir mayor/menor explícitamente.
# Release tag de astral-sh/python-build-standalone — verificar contra
# https://github.com/astral-sh/python-build-standalone/releases antes de cambiar.
_STANDALONE_RELEASE = "20260414"
_STANDALONE_PYTHON_VERSION = "3.13.13"

# Map RuntimeTarget.value → asset filename (install_only flavor — sin dev headers).
# URL canónica: https://github.com/astral-sh/python-build-standalone/releases/download/<release>/<asset>
_STANDALONE_ASSETS: dict[str, str] = {
    "android-arm64": f"cpython-{_STANDALONE_PYTHON_VERSION}+{_STANDALONE_RELEASE}-aarch64-unknown-linux-gnu-install_only.tar.gz",
    "android-armv7": f"cpython-{_STANDALONE_PYTHON_VERSION}+{_STANDALONE_RELEASE}-armv7-unknown-linux-gnueabihf-install_only.tar.gz",
    "linux-x86_64": f"cpython-{_STANDALONE_PYTHON_VERSION}+{_STANDALONE_RELEASE}-x86_64-unknown-linux-gnu-install_only.tar.gz",
    "linux-arm64": f"cpython-{_STANDALONE_PYTHON_VERSION}+{_STANDALONE_RELEASE}-aarch64-unknown-linux-gnu-install_only.tar.gz",
    "darwin-arm64": f"cpython-{_STANDALONE_PYTHON_VERSION}+{_STANDALONE_RELEASE}-aarch64-apple-darwin-install_only.tar.gz",
    "darwin-x86_64": f"cpython-{_STANDALONE_PYTHON_VERSION}+{_STANDALONE_RELEASE}-x86_64-apple-darwin-install_only.tar.gz",
    "windows-x86_64": f"cpython-{_STANDALONE_PYTHON_VERSION}+{_STANDALONE_RELEASE}-x86_64-pc-windows-msvc-install_only.tar.gz",
}

# pip `--platform` tag por target (manylinux2014 es el baseline aceptado por PyPI
# para wheels Linux, compatible con glibc≥2.17; musllinux si aparece un target
# musl-based como Alpine). Windows/Darwin tienen sus propios tags.
_PIP_PLATFORM_TAGS: dict[str, list[str]] = {
    "android-arm64": ["manylinux2014_aarch64", "manylinux_2_17_aarch64"],
    "android-armv7": ["manylinux2014_armv7l", "manylinux_2_17_armv7l"],
    "linux-x86_64": ["manylinux2014_x86_64", "manylinux_2_17_x86_64"],
    "linux-arm64": ["manylinux2014_aarch64", "manylinux_2_17_aarch64"],
    "darwin-arm64": ["macosx_11_0_arm64"],
    "darwin-x86_64": ["macosx_10_13_x86_64"],
    "windows-x86_64": ["win_amd64"],
}

# python-build-standalone layout — el tarball extrae un único `python/` top-level.
_STANDALONE_ROOT = "python"


def _standalone_cache_dir() -> Path:
    """Directorio local para cachear tarballs de python-build-standalone.

    Evita re-descargar el mismo asset en cada build (varias targets en CI,
    retries locales). Reusa patrón del user-cache multi-plataforma.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    out = base / "gimo" / "runtime-python" / _STANDALONE_RELEASE
    out.mkdir(parents=True, exist_ok=True)
    return out


def _standalone_url(target: RuntimeTarget) -> str:
    asset = _STANDALONE_ASSETS.get(target.value)
    if not asset:
        raise SystemExit(
            f"target {target.value!r} no tiene asset python-build-standalone mapeado. "
            f"Añade la entry en _STANDALONE_ASSETS o usa --python-source=host."
        )
    return (
        "https://github.com/astral-sh/python-build-standalone/releases/download/"
        f"{_STANDALONE_RELEASE}/{asset}"
    )


def _pip_platform_for(target: RuntimeTarget) -> List[str]:
    tags = _PIP_PLATFORM_TAGS.get(target.value)
    if not tags:
        raise SystemExit(
            f"target {target.value!r} no tiene pip --platform tag mapeado. "
            f"Añade la entry en _PIP_PLATFORM_TAGS o usa --python-source=host."
        )
    return tags


def _download_with_retries(url: str, dest: Path, *, retries: int = 3) -> None:
    """Descarga idempotente con retries lineales."""
    if dest.exists() and dest.stat().st_size > 0:
        logger.info("standalone cache hit: %s", dest)
        return
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            logger.info("downloading %s (attempt %d/%d)", url, attempt, retries)
            with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (URL is HTTPS constant)
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status} on {url}")
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as fh:
                    shutil.copyfileobj(resp, fh)
                tmp.rename(dest)
            return
        except Exception as exc:  # pragma: no cover — retry path
            last_err = exc
            logger.warning("download failed (%s); retry=%d", exc, attempt)
    raise SystemExit(f"failed to download {url} after {retries} retries: {last_err}")


def _fetch_standalone_python(
    target: RuntimeTarget,
    staging_python: Path,
) -> str:
    """Descarga + extrae python-build-standalone al `staging_python/`.

    Returns:
        Ruta relativa (POSIX) al binario Python dentro del bundle extraído.
    """
    url = _standalone_url(target)
    cache = _standalone_cache_dir()
    asset_name = _STANDALONE_ASSETS[target.value]
    cached_tarball = cache / asset_name

    _download_with_retries(url, cached_tarball)

    # El tarball extrae un único `python/` root. Lo normalizamos al `staging_python/`.
    logger.info("extracting standalone python → %s", staging_python)
    if staging_python.exists():
        shutil.rmtree(staging_python)
    staging_python.mkdir(parents=True, exist_ok=True)
    with tarfile.open(cached_tarball, "r:gz") as tf:
        # Extract directly; python-build-standalone archives wrap todo en `python/`.
        # Para que el resultado viva en `staging_python/` (no `staging_python/python/`),
        # extraemos a un tmp y movemos el contenido.
        tmp_extract = staging_python.with_name(staging_python.name + "-extract")
        if tmp_extract.exists():
            shutil.rmtree(tmp_extract)
        tmp_extract.mkdir(parents=True)
        tf.extractall(tmp_extract)  # noqa: S202 (trusted tarball from pinned asset)

    src_root = tmp_extract / _STANDALONE_ROOT
    if not src_root.exists():
        raise SystemExit(
            f"python-build-standalone layout inesperado — no se encontró {src_root}"
        )
    # Move children of src_root → staging_python
    for child in src_root.iterdir():
        shutil.move(str(child), str(staging_python / child.name))
    shutil.rmtree(tmp_extract, ignore_errors=True)

    # El entry-point difiere por target.
    if target.value.startswith("windows-"):
        exe_rel = "python.exe"
    else:
        exe_rel = f"bin/python{sys.version_info.major}.{sys.version_info.minor}"
        # python-build-standalone ships bin/python3 symlink + bin/python3.X binary
        # Verificamos que al menos uno exista; el bootstrap sabe seguir symlinks.
        candidate = staging_python / exe_rel
        if not candidate.exists():
            alt = staging_python / "bin" / "python3"
            if alt.exists():
                exe_rel = "bin/python3"
    return exe_rel


def _install_wheels_cross(
    requirements: Path,
    site_packages: Path,
    *,
    target: RuntimeTarget,
    python_version: str,
) -> None:
    """Cross-compile wheels via ``pip install --platform``.

    Falla duro si alguna dep no publica wheel compatible con el target — eso es
    *deliberado*: un cross-compile silencioso (sin wheels nativas) produciría
    un bundle que colapsa en runtime con ``ModuleNotFoundError`` sobre módulos
    C no presentes.
    """
    logger.info(
        "installing wheels (cross) for target=%s python=%s → %s",
        target.value, python_version, site_packages,
    )
    site_packages.mkdir(parents=True, exist_ok=True)

    # pip cross-install flags — NO pasamos `--implementation` / `--abi` porque
    # eso excluye wheels pure-Python (`py3-none-any`), y muchas deps GIMO
    # (starlette, pydantic-settings, fastmcp) son pure-Python. Con `--platform`
    # + `--only-binary` + `--python-version`, pip hace el matching correcto:
    # acepta wheels pure-Python (`py3-none-any`) Y wheels nativos del platform
    # pedido, pero rechaza source dists.
    args = [
        sys.executable, "-m", "pip", "install",
        "--quiet",
        "--target", str(site_packages),
        "--only-binary", ":all:",
        "--python-version", python_version,
    ]
    for tag in _pip_platform_for(target):
        args.extend(["--platform", tag])
    args.extend(["--requirement", str(requirements)])
    subprocess.run(args, check=True)


# --------------------------------------------------------------------- helpers
def detect_host_target() -> RuntimeTarget:
    """Mapea la máquina actual a un valor ``RuntimeTarget``.

    Soporta los targets donde Python existe nativamente como Desktop.
    Para Android la detección siempre retorna el valor que el build solicita
    explícitamente — nunca se detecta en host.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        if machine in ("x86_64", "amd64"):
            return RuntimeTarget.linux_x86_64
        if machine in ("aarch64", "arm64"):
            return RuntimeTarget.linux_arm64
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            return RuntimeTarget.darwin_arm64
        if machine in ("x86_64", "amd64"):
            return RuntimeTarget.darwin_x86_64
    elif system == "windows":
        if machine in ("amd64", "x86_64"):
            return RuntimeTarget.windows_x86_64

    raise SystemExit(
        f"Unsupported host platform: system={system!r} machine={machine!r}. "
        "Compilar cross-platform requiere el CI (step 9 del plan RUNTIME_PACKAGING)."
    )


def _target_matches_host(target: RuntimeTarget) -> bool:
    try:
        return target == detect_host_target()
    except SystemExit:
        return False


def _copy_tree(src: Path, dst: Path, *, rel_to: Path) -> List[str]:
    """Copia un archivo/directorio conservando la jerarquía relativa a ``rel_to``.

    Returns:
        Lista de rutas relativas (POSIX style) copiadas — para el manifest.
    """
    rels: List[str] = []
    if src.is_file():
        target = dst / src.relative_to(rel_to)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        rels.append(str(src.relative_to(rel_to)).replace("\\", "/"))
        return rels

    for path in src.rglob("*"):
        if path.is_dir():
            continue
        # Skip compilados e intermedios
        if "__pycache__" in path.parts:
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        rel_from_root = path.relative_to(rel_to)
        target = dst / rel_from_root
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        rels.append(str(rel_from_root).replace("\\", "/"))
    return rels


def _install_wheels(requirements: Path, site_packages: Path) -> None:
    """Instala las deps de ``requirements.txt`` en ``site_packages``.

    Usa el pip del intérprete actual con ``--target`` — semántica idéntica
    a la que usará el CI cuando instale con ``--platform`` para cross-compile.
    """
    logger.info("installing wheels into %s", site_packages)
    site_packages.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--target",
            str(site_packages),
            "--requirement",
            str(requirements),
        ],
        check=True,
    )


def _bundle_host_python(output_python: Path) -> str:
    """Empaqueta el CPython del host actual.

    Para develop local (`--target host`) copiamos la instalación del sistema
    a `output_python/`. El layout resultante replica lo que
    python-build-standalone produce para el CI (bin/ + lib/ + include/).

    Returns:
        ruta relativa (POSIX) al binario Python dentro del bundle.
    """
    python_home = Path(sysconfig.get_config_var("prefix"))
    output_python.mkdir(parents=True, exist_ok=True)

    # Replicar bin/ (o Scripts/ en Windows) + lib/ (o Lib/).
    if platform.system().lower() == "windows":
        bin_src = python_home
        bin_dst = output_python
        lib_src = python_home / "Lib"
        lib_dst = output_python / "Lib"
        exe_name = "python.exe"
        exe_rel = exe_name
    else:
        bin_src = python_home / "bin"
        bin_dst = output_python / "bin"
        lib_src = python_home / "lib"
        lib_dst = output_python / "lib"
        exe_name = f"python{sys.version_info.major}.{sys.version_info.minor}"
        exe_rel = f"bin/{exe_name}"

    # Copiar mínimo: el binario + la stdlib.
    # stdlib: typically en lib/pythonX.Y/ — copiamos completa.
    stdlib_name = f"python{sys.version_info.major}.{sys.version_info.minor}"

    # Binario
    bin_dst.mkdir(parents=True, exist_ok=True)
    exe_src = bin_src / exe_name
    if not exe_src.exists() and platform.system().lower() == "windows":
        # Windows a veces es `python.exe` directamente en prefix
        exe_src = python_home / exe_name
    if not exe_src.exists():
        raise SystemExit(f"python binary not found at {exe_src}")
    shutil.copy2(exe_src, bin_dst / exe_name)

    # stdlib
    if platform.system().lower() == "windows":
        # Windows: Lib/ contiene toda la stdlib + site-packages
        if lib_src.exists():
            _copy_stdlib(lib_src, lib_dst)
    else:
        stdlib_src = lib_src / stdlib_name
        stdlib_dst = lib_dst / stdlib_name
        if stdlib_src.exists():
            _copy_stdlib(stdlib_src, stdlib_dst)

    return exe_rel


def _copy_stdlib(src: Path, dst: Path) -> None:
    """Copia la stdlib filtrando archivos no esenciales para reducir tamaño."""
    dst.mkdir(parents=True, exist_ok=True)
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        if "__pycache__" in path.parts:
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        # Filter site-packages propias del host (las wheels del Core viven
        # aparte en el bundle).
        if "site-packages" in path.parts:
            continue
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _build_repo_tree(repo_root: Path, bundle_repo: Path) -> List[str]:
    """Copia los subdirectorios/archivos del repo necesarios en runtime."""
    files: List[str] = []
    for rel in _REPO_INCLUDES:
        src = repo_root / rel
        if not src.exists():
            logger.warning("repo include missing, skipping: %s", rel)
            continue
        files.extend(_copy_tree(src, bundle_repo, rel_to=repo_root))
    return files


def _walk_files(root: Path) -> List[str]:
    """Lista de rutas relativas POSIX de todos los archivos bajo ``root``."""
    out: List[str] = []
    for path in root.rglob("*"):
        if path.is_file():
            out.append(str(path.relative_to(root)).replace("\\", "/"))
    return out


def _compress_bundle(
    staging: Path,
    tarball: Path,
    compression: RuntimeCompression,
) -> None:
    """Comprime ``staging`` en un tarball con el algoritmo pedido."""
    if compression == RuntimeCompression.xz:
        mode = "w:xz"
        preset = {"preset": 6}
    elif compression == RuntimeCompression.none:
        mode = "w"
        preset = {}
    elif compression == RuntimeCompression.zstd:
        raise SystemExit(
            "zstd compression todavia no implementada en el productor "
            "(MVP usa xz). Follow-up documentado en el plan."
        )
    else:
        raise SystemExit(f"unknown compression: {compression}")

    logger.info("compressing bundle → %s", tarball.name)
    with tarfile.open(tarball, mode=mode, **preset) as tf:  # type: ignore[arg-type]
        for entry in sorted(staging.iterdir()):
            tf.add(entry, arcname=entry.name)


# --------------------------------------------------------------------- commands
def cmd_detect_target(_args: argparse.Namespace) -> int:
    print(detect_host_target().value)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    target = RuntimeTarget(args.target) if args.target != "host" else detect_host_target()
    compression = RuntimeCompression(args.compression)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    # CROSS_COMPILE (2026-04-16): con `--python-source=standalone` aceptamos cross
    # target. El guard de "host only" se reserva para la ruta default donde no
    # hay toolchain cross disponible.
    python_source = getattr(args, "python_source", "host")
    if python_source == "host" and not _target_matches_host(target):
        raise SystemExit(
            f"target {target.value!r} requires cross-compilation and --python-source=host is set. "
            f"Use `--python-source=standalone` to fetch python-build-standalone, "
            f"or run through the CI matrix with the appropriate target."
        )

    private_key_pem = args.signing_key
    if not private_key_pem:
        env_val = os.environ.get("ORCH_RUNTIME_SIGNING_KEY", "")
        if env_val:
            private_key_pem = env_val.replace("\\n", "\n")
    if not private_key_pem:
        raise SystemExit(
            "signing key not provided. Use --signing-key <path|pem> or set "
            "ORCH_RUNTIME_SIGNING_KEY env var."
        )

    if os.path.exists(private_key_pem):
        private_key_pem = Path(private_key_pem).read_text(encoding="utf-8")

    staging = output / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Python runtime
        if python_source == "standalone":
            python_rel = _fetch_standalone_python(target, staging / "python")
        else:
            python_rel = _bundle_host_python(staging / "python")

        # 2. Wheels
        if python_source == "standalone":
            _install_wheels_cross(
                _REPO_ROOT / _REQUIREMENTS_FILE,
                staging / "site-packages",
                target=target,
                python_version=_STANDALONE_PYTHON_VERSION.rsplit(".", 1)[0],  # 3.13
            )
        else:
            _install_wheels(_REPO_ROOT / _REQUIREMENTS_FILE, staging / "site-packages")

        # 3. Repo tree
        _build_repo_tree(_REPO_ROOT, staging / "repo")

        # 4. Lista de archivos
        files = _walk_files(staging)
        uncompressed_bytes = sum(
            (staging / p).stat().st_size for p in files if (staging / p).is_file()
        )

        # 5. Comprimir
        suffix = {
            RuntimeCompression.xz: ".xz",
            RuntimeCompression.none: "",
            RuntimeCompression.zstd: ".zst",
        }[compression]
        tarball_name = _TARBALL_NAME + suffix
        tarball_path = output / tarball_name
        if tarball_path.exists():
            tarball_path.unlink()
        _compress_bundle(staging, tarball_path, compression)

        # 6. Hash + manifest
        sha = sha256_file(str(tarball_path))
        compressed_bytes = tarball_path.stat().st_size

        manifest = RuntimeManifest(
            runtime_version=args.runtime_version,
            target=target,
            compression=compression,
            tarball_name=tarball_name,
            tarball_sha256=sha,
            compressed_size_bytes=compressed_bytes,
            uncompressed_size_bytes=uncompressed_bytes,
            python_rel_path=f"python/{python_rel}",
            repo_root_rel_path="repo",
            python_path_entries=["repo", "site-packages"],
            files=files,
            extra_env={"PYTHONDONTWRITEBYTECODE": "1"},
            signature="0" * 128,  # placeholder, replaced below
            python_version=".".join(str(v) for v in sys.version_info[:3]),
            built_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            builder=args.builder or "local-dev",
        )

        # 7. Firmar
        try:
            sig = sign_manifest(manifest, private_key_pem)
        except RuntimeSignatureError as exc:
            raise SystemExit(f"signing failed: {exc}")
        manifest = manifest.model_copy(update={"signature": sig})

        # 8. Escribir manifest + .sig
        (output / _MANIFEST_NAME).write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        (output / _SIG_NAME).write_text(sig, encoding="utf-8")

        logger.info(
            "bundle ready → %s (compressed=%.1f MiB, uncompressed=%.1f MiB, ratio=%.2fx)",
            tarball_path.name,
            compressed_bytes / (1024 * 1024),
            uncompressed_bytes / (1024 * 1024),
            (uncompressed_bytes / compressed_bytes) if compressed_bytes else 0.0,
        )
    finally:
        # Limpiamos staging siempre — el artefacto final vive fuera.
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from tools.gimo_server.security.runtime_signature import verify_manifest

    bundle_dir = Path(args.bundle).resolve()
    manifest_path = bundle_dir / _MANIFEST_NAME
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")

    manifest = RuntimeManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

    tarball_path = bundle_dir / manifest.tarball_name
    if not tarball_path.exists():
        raise SystemExit(f"tarball missing: {tarball_path}")

    actual_sha = sha256_file(str(tarball_path))
    if actual_sha != manifest.tarball_sha256:
        raise SystemExit(
            f"sha256 mismatch: manifest={manifest.tarball_sha256} actual={actual_sha}"
        )

    pub_key_pem: Optional[str] = None
    if args.public_key:
        pub_key_pem = Path(args.public_key).read_text(encoding="utf-8")

    if not verify_manifest(manifest, pub_key_pem):
        raise SystemExit("signature verification FAILED")

    print(f"OK — version={manifest.runtime_version} target={manifest.target.value}")
    return 0


# --------------------------------------------------------------------- entry
def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="package_core_runtime",
        description="GIMO Core runtime bundle packager",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("detect-target", help="Print the host target tuple")

    build = sub.add_parser("build", help="Produce a signed runtime bundle")
    build.add_argument("--target", default="host", help="Target (default: host)")
    build.add_argument(
        "--output", required=True, help="Output directory (will be created if missing)"
    )
    build.add_argument(
        "--compression",
        default=RuntimeCompression.xz.value,
        choices=[c.value for c in RuntimeCompression],
    )
    build.add_argument(
        "--runtime-version", required=True, help="SemVer of this build (e.g. 0.1.0)"
    )
    build.add_argument(
        "--signing-key",
        help="Path to Ed25519 private PEM, or the PEM string itself",
    )
    build.add_argument(
        "--builder",
        help="Identifier of the builder (CI job id, local-dev, etc.)",
    )
    build.add_argument(
        "--python-source",
        default="host",
        choices=["host", "standalone"],
        help=(
            "Source del intérprete Python del bundle. 'host' empaqueta el Python "
            "del script actual (limitado a target matching host). 'standalone' "
            "descarga python-build-standalone para el target pedido — requisito "
            "para cross-compile real (android-arm64, darwin-arm64, etc.)."
        ),
    )

    verify = sub.add_parser("verify", help="Verify a bundle's signature and hash")
    verify.add_argument("--bundle", required=True, help="Path to bundle directory")
    verify.add_argument(
        "--public-key", help="Path to Ed25519 public PEM (defaults to env/embedded)"
    )

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = _build_argparser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "detect-target":
        return cmd_detect_target(args)
    if args.command == "build":
        return cmd_build(args)
    if args.command == "verify":
        return cmd_verify(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
