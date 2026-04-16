"""
Runtime Upgrader — Peer-to-peer Core upgrade
============================================
Cliente para bajar un bundle GIMO Core desde un peer del mesh (o desde un
endpoint HTTP arbitrario) y promoverlo al runtime activo local.

Flujo canónico:

1. GET ``{peer}/ops/mesh/runtime-manifest`` → compara ``runtime_version``
   contra el manifest actual (si existe).
2. Si ambos coinciden → no-op (idempotente; retorna ``UpgradeOutcome.UP_TO_DATE``).
3. GET ``{peer}/ops/mesh/runtime-payload`` → stream al tarball dentro de una
   carpeta de staging. Si hay ``Range``-able y existe un download parcial
   previo (``.download-partial``), reanuda.
4. Verifica sha256 del tarball vs el declarado en el manifest descargado.
5. Valida la firma Ed25519 del manifest (reusa ``verify_manifest``).
6. Escribe ``<assets_dir>/gimo-core-runtime.tar.xz`` + ``.json`` + ``.sig``
   atómicamente (rename desde staging).
7. Invoca ``runtime_bootstrap.ensure_extracted`` para promover el bundle
   a ``<target_dir>`` (atomic swap + marker).

El módulo es **CANÓNICO** — el CLI ``gimo runtime upgrade`` lo invoca y un
eventual Android UI hace exactamente lo mismo. La clave pública embebida /
``ORCH_RUNTIME_PUBLIC_KEY`` debe coincidir; no hay trust-on-first-use.

Rev 0 — 2026-04-16 (plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING step 8).
"""
from __future__ import annotations

import enum
import hashlib
import logging
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

from tools.gimo_server.models.runtime import RuntimeManifest
from tools.gimo_server.security.runtime_signature import verify_manifest
from tools.gimo_server.services.runtime_bootstrap import (
    BootstrapResult,
    RuntimeBootstrapError,
    ensure_extracted,
)

logger = logging.getLogger("orchestrator.runtime_upgrader")


_MANIFEST_PATH = "/ops/mesh/runtime-manifest"
_PAYLOAD_PATH = "/ops/mesh/runtime-payload"
_MANIFEST_FILE = "gimo-core-runtime.json"
_SIG_FILE = "gimo-core-runtime.sig"
_PARTIAL_SUFFIX = ".download-partial"


class RuntimeUpgradeError(RuntimeError):
    """Cualquier fallo durante el upgrade peer-to-peer."""


class UpgradeOutcome(str, enum.Enum):
    UP_TO_DATE = "up_to_date"
    UPGRADED = "upgraded"
    DOWNGRADED = "downgraded"  # remote < local; requiere --allow-downgrade


@dataclass(frozen=True)
class UpgradeResult:
    outcome: UpgradeOutcome
    from_version: Optional[str]
    to_version: str
    bootstrap: Optional[BootstrapResult]
    bytes_transferred: int


# ── HTTP helpers ─────────────────────────────────────────────────────────────
def _auth_headers(token: str) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _http_get_json(url: str, token: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers={**_auth_headers(token), "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            import json
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeUpgradeError(
            f"GET {url} → HTTP {exc.code}: {exc.reason}. "
            f"Verifica ORCH_TOKEN y que el peer tenga un bundle publicado."
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeUpgradeError(f"GET {url} unreachable: {exc.reason}") from exc


def _http_download(
    url: str,
    token: str,
    dest: Path,
    *,
    resume_from: int = 0,
    timeout: float = 120.0,
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
) -> int:
    """Descarga ``url`` a ``dest``. Soporta reanudación si resume_from > 0.

    Returns bytes totales ESCRITOS a ``dest`` (incluye los pre-existentes si reanuda).
    """
    headers = {**_auth_headers(token), "Accept": "application/octet-stream"}
    mode = "wb"
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"
        mode = "ab"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            total_remote: Optional[int] = None
            if status == 206:
                # Content-Range: bytes start-end/total
                cr = resp.headers.get("Content-Range", "")
                if "/" in cr:
                    try:
                        total_remote = int(cr.rsplit("/", 1)[1])
                    except ValueError:
                        total_remote = None
            elif status == 200:
                cl = resp.headers.get("Content-Length")
                if cl:
                    try:
                        total_remote = int(cl)
                    except ValueError:
                        total_remote = None
                if resume_from > 0:
                    # Server ignoró Range — empezamos de cero
                    resume_from = 0
                    mode = "wb"
            else:
                raise RuntimeUpgradeError(f"unexpected HTTP {status} from {url}")

            dest.parent.mkdir(parents=True, exist_ok=True)
            written = resume_from
            with open(dest, mode) as fh:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
                    if on_progress is not None:
                        on_progress(written, total_remote)
            return written
    except urllib.error.HTTPError as exc:
        raise RuntimeUpgradeError(
            f"GET {url} → HTTP {exc.code}: {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeUpgradeError(f"GET {url} unreachable: {exc.reason}") from exc


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_local_manifest(assets_dir: Path) -> Optional[RuntimeManifest]:
    mp = assets_dir / _MANIFEST_FILE
    if not mp.exists():
        return None
    try:
        return RuntimeManifest.model_validate_json(mp.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("local manifest invalid (%s); treating as absent", exc)
        return None


def _normalize_peer_url(peer_url: str) -> str:
    """Admite tanto ``http://host:port`` como ``http://host:port/`` o con path."""
    if not peer_url:
        raise RuntimeUpgradeError("peer_url vacío")
    parts = urlsplit(peer_url)
    if not parts.scheme or not parts.netloc:
        raise RuntimeUpgradeError(f"peer_url inválido: {peer_url!r}")
    return f"{parts.scheme}://{parts.netloc}"


# ── Semver compare (simple, suficiente para MVP) ─────────────────────────────
def _parse_semver(v: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in v.split("-", 1)[0].split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


def _compare_versions(a: str, b: str) -> int:
    pa, pb = _parse_semver(a), _parse_semver(b)
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


# ── Público ──────────────────────────────────────────────────────────────────
def upgrade_from_peer(
    peer_url: str,
    *,
    assets_dir: Path,
    target_dir: Path,
    token: str = "",
    public_key_pem: Optional[str] = None,
    allow_unsigned: bool = False,
    allow_downgrade: bool = False,
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
    skip_exec_probe: bool = False,
) -> UpgradeResult:
    """Descarga el bundle del peer y lo promueve al runtime activo local.

    Args:
        peer_url: base URL del peer, p.ej. ``http://192.168.1.50:9325``.
        assets_dir: carpeta local donde viven los artefactos del bundle
            (manifest + tarball + sig). Tras upgrade contiene los nuevos.
        target_dir: destino donde ``ensure_extracted`` expande.
        token: ORCH_TOKEN del peer (para auth del GET).
        public_key_pem: clave pública Ed25519 esperada. ``None`` = usa
            ``ORCH_RUNTIME_PUBLIC_KEY`` env var / embebida.
        allow_unsigned: escape hatch para tests. NUNCA usar en prod.
        allow_downgrade: permite que remote.version < local.version.
        on_progress: callback ``(bytes_written, total_expected_or_None)``.
        skip_exec_probe: BUGS_LATENTES §H8. Propaga al ``ensure_extracted``
            interno. Los tests con bundles sintéticos sin python real deben
            pasar ``True``. En producción siempre ``False`` (default) para
            que el probe atrape ABI mismatch post-upgrade temprano.

    Returns:
        :class:`UpgradeResult` con outcome y versiones involucradas.

    Raises:
        RuntimeUpgradeError: red, HTTP, firma, sha mismatch, o versión más baja
            sin ``allow_downgrade``.
        RuntimeBootstrapError: si ``ensure_extracted`` falla después del swap.
    """
    base = _normalize_peer_url(peer_url)
    assets_dir = Path(assets_dir).resolve()
    target_dir = Path(target_dir).resolve()

    local_manifest = _read_local_manifest(assets_dir)
    local_version = local_manifest.runtime_version if local_manifest else None

    # 1. Fetch remote manifest
    remote_raw = _http_get_json(base + _MANIFEST_PATH, token)
    try:
        remote_manifest = RuntimeManifest.model_validate(remote_raw)
    except Exception as exc:
        raise RuntimeUpgradeError(f"remote manifest schema invalid: {exc}") from exc

    # 2. Firma remota — validar antes de bajar el payload (bail-early)
    if not allow_unsigned and not verify_manifest(remote_manifest, public_key_pem):
        raise RuntimeUpgradeError(
            "remote manifest signature verification failed — abortando upgrade"
        )

    # 3. Compare versions
    if local_version is not None:
        cmp = _compare_versions(remote_manifest.runtime_version, local_version)
        if cmp == 0:
            logger.info(
                "peer runtime %s matches local — no-op",
                remote_manifest.runtime_version,
            )
            return UpgradeResult(
                outcome=UpgradeOutcome.UP_TO_DATE,
                from_version=local_version,
                to_version=remote_manifest.runtime_version,
                bootstrap=None,
                bytes_transferred=0,
            )
        if cmp < 0 and not allow_downgrade:
            raise RuntimeUpgradeError(
                f"peer runtime {remote_manifest.runtime_version} is older than "
                f"local {local_version}. Use allow_downgrade=True si intencional."
            )

    # 4. Stage del tarball + sig + manifest en assets_dir (atomic rename al final).
    assets_dir.mkdir(parents=True, exist_ok=True)
    partial = assets_dir / (remote_manifest.tarball_name + _PARTIAL_SUFFIX)
    resume_from = partial.stat().st_size if partial.exists() else 0

    bytes_total = _http_download(
        base + _PAYLOAD_PATH,
        token,
        partial,
        resume_from=resume_from,
        on_progress=on_progress,
    )

    # 5. Verificar sha256
    actual_sha = _sha256_file(partial)
    if actual_sha != remote_manifest.tarball_sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeUpgradeError(
            f"tarball sha256 mismatch: manifest={remote_manifest.tarball_sha256} "
            f"actual={actual_sha}. Archivo parcial descartado — reintenta."
        )

    # 6. Promover: .download-partial → tarball_name, y escribir manifest + sig.
    final_tarball = assets_dir / remote_manifest.tarball_name
    if final_tarball.exists():
        final_tarball.unlink()
    os.replace(partial, final_tarball)

    (assets_dir / _MANIFEST_FILE).write_text(
        remote_manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    (assets_dir / _SIG_FILE).write_text(remote_manifest.signature, encoding="utf-8")

    # 7. Expandir con el helper canónico.
    try:
        bootstrap = ensure_extracted(
            assets_dir,
            target_dir,
            public_key_pem=public_key_pem,
            allow_unsigned=allow_unsigned,
            skip_exec_probe=skip_exec_probe,
        )
    except RuntimeBootstrapError:
        # Mantenemos los artefactos nuevos en assets_dir para inspección;
        # target_dir queda como estaba por los rollbacks de ensure_extracted.
        raise

    outcome = UpgradeOutcome.UPGRADED
    if local_version is not None and _compare_versions(remote_manifest.runtime_version, local_version) < 0:
        outcome = UpgradeOutcome.DOWNGRADED

    logger.info(
        "runtime upgrade complete: %s → %s (bytes=%d)",
        local_version or "<none>", remote_manifest.runtime_version, bytes_total,
    )
    return UpgradeResult(
        outcome=outcome,
        from_version=local_version,
        to_version=remote_manifest.runtime_version,
        bootstrap=bootstrap,
        bytes_transferred=bytes_total,
    )
