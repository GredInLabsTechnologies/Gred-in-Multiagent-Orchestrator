#!/usr/bin/env python3
"""
build_rove_wheelhouse.py — GIMO Core wheelhouse builder
========================================================
Wrapper que usa :mod:`rove.builder` con el flag correcto de ``--platform``
para cross-compile real (el CLI oficial de rove 1.0.0 no expone ese flag:
``extra_args`` sí existe en ``PipRunOptions`` pero ``rove.cli.build_cmd``
no lo setea, por lo que en Windows termina bajando wheels win_amd64
aunque el target sea android-arm64).

Este script resuelve ese gap:

1. Lee ``rove.toml`` (config canónico — ``project_name``, ``requirements``,
   ``targets``, ``patches``, ``sign_key``).
2. Para targets Android pasa ``--platform manylinux2014_aarch64`` y
   ``--only-binary=:all:`` al pip download interno — así pip devuelve
   wheels aarch64-linux (compatibles con Android/Termux) en vez de los
   del host.
3. Aplica el patch set ``vendor/rove-patches/`` (env vars + toml overrides).
4. Construye el tarball vía :func:`rove.builder.tarball.build_tarball`.
5. Firma con la private key indicada en ``rove.toml.sign_key``.

Uso:
    # Build bundle para Android (primary mesh target)
    python scripts/build_rove_wheelhouse.py --target android-arm64

    # Verificar lo producido
    python -m rove.cli verify --bundle dist/gimo-core-android-arm64-*.tar.xz

Salida:
    dist/gimo-core-<target>-<version>.tar.xz             (wheelhouse+repo)
    dist/gimo-core-<target>-<version>.tar.xz.manifest.json  (firmado)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rove.config import RoveConfig, load as load_rove_config  # noqa: E402
from rove.manifest import Compression, Target  # noqa: E402
from rove.patches.loader import PatchKind, load_patch_set, resolve_patches  # noqa: E402
from rove.builder.patches import (  # noqa: E402
    apply_env_patches,
    read_toml_overrides,
)
from rove.builder.pip_runner import (  # noqa: E402
    PipRunOptions,
    run_pip_download,
)
from rove.builder.tarball import (  # noqa: E402
    TarballBuildOptions,
    build_tarball,
)
from rove.builder.zig import build_env_for, ZigNotFoundError  # noqa: E402
from rove.signing.ed25519 import sign_manifest  # noqa: E402
from rove.targets import detect_host, parse as parse_target, resolve as resolve_target  # noqa: E402

logger = logging.getLogger("build_rove_wheelhouse")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


# pip --platform tags por target. Coinciden con scripts/package_core_runtime.py
# que ya los mapeaba — fuente única en rove.targets sería mejor, pero
# upstream no lo expone todavía.
_PIP_PLATFORMS: dict[str, list[str]] = {
    "android-arm64": ["manylinux2014_aarch64", "manylinux_2_17_aarch64"],
    "android-armv7": ["manylinux2014_armv7l", "manylinux_2_17_armv7l"],
    # Android x86_64 (emulator Google Play, Chromebook ARC, tablets x86).
    # Usamos los tags manylinux x86_64 — pip no distingue android vs linux
    # para ABIs Intel y en la práctica los wheels manylinux corren en ambos.
    "android-x86_64": ["manylinux2014_x86_64", "manylinux_2_17_x86_64"],
    "linux-x86_64": ["manylinux2014_x86_64", "manylinux_2_17_x86_64"],
    "linux-arm64": ["manylinux2014_aarch64", "manylinux_2_17_aarch64"],
    "darwin-arm64": ["macosx_11_0_arm64"],
    "darwin-x86_64": ["macosx_10_13_x86_64"],
    "windows-x86_64": ["win_amd64"],
}


def _cross_args(target: Target, python_version: str) -> list[str]:
    """Args extras para cross-compile via pip download.

    Para targets distintos al host, pedimos platform tags específicos y
    ``--only-binary=:all:`` para rechazar sdists (si una dep no tiene
    wheel nativo, fallamos rápido en vez de compilar desde el host que
    produciría binario incorrecto).
    """
    tags = _PIP_PLATFORMS.get(target.value, [])
    args: list[str] = [
        "--only-binary", ":all:",
        "--python-version", python_version,
    ]
    for tag in tags:
        args.extend(["--platform", tag])
    return args


def _resolve_sign_key(cfg_key: str | None) -> str:
    """Resuelve la clave privada PEM para firmar el manifest.

    Acepta path absoluto/relativo o contenido PEM directo. Si el campo
    empieza con ``-----BEGIN``, se trata como PEM literal.
    """
    if not cfg_key:
        # Fallback: archivo local en secrets/
        candidate = _REPO_ROOT / "secrets" / "runtime-signing.pem"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
        raise RuntimeError(
            "no sign_key declared in rove.toml and secrets/runtime-signing.pem "
            "does not exist. Generate with `python -m rove.cli keygen`."
        )

    # Expansión de env vars format ${VAR} o ${VAR:default}
    if cfg_key.startswith("${") and cfg_key.endswith("}"):
        spec = cfg_key[2:-1]
        if ":" in spec:
            name, default = spec.split(":", 1)
            raw = os.environ.get(name, "").strip() or default
        else:
            raw = os.environ.get(spec, "").strip()
        cfg_key = raw

    if cfg_key.startswith("-----BEGIN"):
        return cfg_key

    # Path (absolute or relative to repo root)
    key_path = Path(cfg_key)
    if not key_path.is_absolute():
        key_path = _REPO_ROOT / key_path
    return key_path.read_text(encoding="utf-8")


def _copy_project_subset(
    includes: list[str],
    excludes: list[str],
    dest: Path,
) -> None:
    """Copia el subset del repo al staging del bundle, respetando excludes.

    rove's ``build_tarball`` espera un ``project_root`` que ES el subset final
    — no filtra internamente por glob. Pre-filtramos aquí.
    """
    import fnmatch
    import shutil

    def _excluded(rel: str) -> bool:
        norm = rel.replace("\\", "/")
        for pat in excludes:
            if fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(f"/{norm}", f"/{pat}"):
                return True
            if pat.startswith("**/") and fnmatch.fnmatch(norm, pat):
                return True
        return False

    for entry in includes:
        src = _REPO_ROOT / entry
        if not src.exists():
            logger.warning("include missing, skipping: %s", entry)
            continue
        target = dest / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            if _excluded(entry):
                continue
            shutil.copy2(src, target)
        else:
            for sub in src.rglob("*"):
                if sub.is_dir():
                    continue
                rel = sub.relative_to(_REPO_ROOT)
                if _excluded(str(rel)):
                    continue
                dst = dest / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sub, dst)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GIMO Core wheelhouse forge via rove builder API",
    )
    parser.add_argument("--target", required=True, help="android-arm64 / linux-x86_64 / etc.")
    parser.add_argument("--output", default="dist", help="Output directory (default: dist/)")
    parser.add_argument("--python-version", default="3.13")
    parser.add_argument("--compression", default="xz", choices=["xz", "zstd", "none"])
    parser.add_argument(
        "--patch-set",
        default="vendor/rove-patches",
        help="Path to rove-patches registry (default: vendor/rove-patches)",
    )
    args = parser.parse_args()

    # 1. Config + optional locked requirements override
    cfg: RoveConfig = load_rove_config()
    locked_path = _REPO_ROOT / "requirements-locked.txt"
    if locked_path.exists():
        locked_reqs: list[str] = []
        for raw in locked_path.read_text(encoding="utf-8").splitlines():
            s = raw.split("#")[0].strip()
            if s and not s.startswith("-") and not s.startswith("./"):
                locked_reqs.append(s)
        if locked_reqs:
            logger.info("using requirements-locked.txt (%d pinned deps)", len(locked_reqs))
            cfg = cfg.model_copy(update={"requirements": locked_reqs})

    resolved = resolve_target(parse_target(args.target))
    logger.info("target=%s project=%s version=%s", resolved.value, cfg.project_name, cfg.version)

    # 2. Patches
    extra_env: dict[str, str] = {}
    patches_applied: list[str] = []
    patch_dir = _REPO_ROOT / args.patch_set
    if patch_dir.exists():
        patch_set = load_patch_set(patch_dir)
        matches = resolve_patches(
            patch_set,
            packages=[r.split("==")[0].split(">=")[0].split("<")[0].split("[")[0].strip().lower()
                      for r in (cfg.requirements or [])],
            target=resolved,
        )
        non_diff = [p for p in matches if p.kind is not PatchKind.patch]
        extra_env.update(apply_env_patches(non_diff, patch_dir))
        _tomls = read_toml_overrides(non_diff, patch_dir)
        if _tomls:
            logger.info("toml overrides parsed: %d (informational)", len(_tomls))
        patches_applied = [p.id for p in matches]
        logger.info("patches resolved: %d", len(matches))
    else:
        logger.warning("patch-set %s not found — skipping", patch_dir)

    # 3. Zig cross env (ANDROID_API_LEVEL etc. propagated to Rust builds)
    host = detect_host() if True else None  # noqa: SIM108 — keep explicit
    cross_env: dict[str, str] = {}
    if resolved != host:
        try:
            zig_env = build_env_for(resolved)
            cross_env.update(zig_env.extra_env)
            cross_env.setdefault("CC", zig_env.cc)
            cross_env.setdefault("CXX", zig_env.cxx)
            cross_env.setdefault("AR", zig_env.ar)
            logger.info("zig cross env ready: target=%s", zig_env.cargo_build_target)
        except (ZigNotFoundError, ValueError) as exc:
            logger.warning("zig unavailable (%s) — only prebuilt wheels will be fetched", exc)

    # 4. pip download con --platform correcto para cross
    tmp_wheels = Path(tempfile.mkdtemp(prefix="rove-wheels-"))
    merged_env = {**cross_env, **extra_env}
    pip_opts = PipRunOptions(
        requirements=list(cfg.requirements or []),
        target=resolved,
        python_executable=Path(sys.executable),
        output_dir=tmp_wheels,
        prefer_binary=True,
        extra_env=merged_env,
        extra_args=_cross_args(resolved, args.python_version),
        timeout_seconds=1800,
    )
    logger.info("pip download → %d requirements, target=%s", len(pip_opts.requirements), resolved.value)
    pip_result = run_pip_download(pip_opts)
    logger.info("wheels collected: %d", len(pip_result.wheels_collected))

    # 5. Staging project subset (rove's build_tarball takes a finalized project root)
    staging = Path(tempfile.mkdtemp(prefix="rove-staging-"))
    project_root = staging / "project"
    project_root.mkdir(parents=True)
    _copy_project_subset(
        includes=list(cfg.include),
        excludes=list(cfg.exclude),
        dest=project_root,
    )

    # 6. build_tarball (rove handles manifest schema + hashing)
    output_dir = _REPO_ROOT / args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = TarballBuildOptions(
        project_name=cfg.project_name,
        runtime_version=cfg.version or "0.0.0",
        target=resolved,
        compression=Compression(args.compression),
        output_dir=output_dir,
        python_root=None,  # --no-python: consumer provee el interpreter (Termux)
        wheels_dir=tmp_wheels,
        project_root=project_root,
        patches_applied=patches_applied,
    )
    result = build_tarball(opts)
    logger.info("tarball: %s (%.1f MiB)", result.tarball_path.name, result.tarball_path.stat().st_size / (1024*1024))

    # 7. Sign
    sign_pem = _resolve_sign_key(cfg.sign_key)
    signed = sign_manifest(result.manifest, sign_pem)
    # Write signed manifest next to the tarball
    manifest_path = output_dir / f"{result.tarball_path.name}.manifest.json"
    manifest_path.write_text(signed.model_dump_json(indent=2), encoding="utf-8")
    logger.info("manifest (signed): %s", manifest_path.name)
    logger.info("sha256: %s", signed.tarball_sha256)
    return 0


if __name__ == "__main__":
    sys.exit(main())
