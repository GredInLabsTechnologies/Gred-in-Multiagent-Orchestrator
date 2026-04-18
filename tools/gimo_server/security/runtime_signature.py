"""
GIMO Runtime Signature — Thin adapter sobre ``rove.signing.ed25519``
====================================================================
La implementación Ed25519 vive ahora en :mod:`rove.signing.ed25519`
(``rove-toolkit`` v1.0.0 vendorizado en ``vendor/rove/``). Este módulo
preserva la API pública histórica de GIMO para que el resto del codebase
y los tests no tengan que migrar en bloque.

API preservada
--------------
- :data:`EMBEDDED_RUNTIME_PUBLIC_KEY` — clave pública Ed25519 bundled.
  Rotación via ``scripts/generate_runtime_keys.py``.
- :func:`get_runtime_public_key_pem` — env var ``ORCH_RUNTIME_PUBLIC_KEY``
  tiene prioridad, fallback al valor embebido. Distinto del mecanismo de
  rove (``ROVE_TRUSTED_PUBKEYS`` + ``~/.config/rove/trusted_keys/``).
  GIMO conserva su env var por continuidad operacional.
- :func:`sign_manifest(manifest, private_key_pem) -> str` — devuelve hex
  string de 128 chars. Rove devuelve un ``WheelhouseManifest`` nuevo;
  extraemos ``.signature`` para preservar el contrato histórico.
- :func:`verify_manifest(manifest, public_key_pem=None) -> bool` — nunca
  raisea. Rove's ``verify_manifest`` raisea :class:`RuntimeSignatureError`
  cuando no hay ninguna trusted key configurada; nosotros lo absorbemos
  y devolvemos ``False`` para no romper callers que tratan el retorno
  como booleano plano.
- :func:`sha256_file(path, chunk_size=1MiB) -> str` — delega en rove
  preservando el chunk size histórico (rove default es 64 KiB).

Migración a rove 1.0.0 — 2026-04-18 (ver ``vendor/rove/README.md``).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from rove.manifest import WheelhouseManifest
from rove.signing.ed25519 import (
    RuntimeSignatureError,
    sha256_file as _rove_sha256_file,
    sign_manifest as _rove_sign_manifest,
    verify_manifest as _rove_verify_manifest,
)

logger = logging.getLogger("orchestrator.runtime_signature")


# Clave pública Ed25519 embebida. Generada con
# ``scripts/generate_runtime_keys.py`` (plan CROSS_COMPILE §Change 5).
# La clave privada asociada vive en ``secrets/runtime-signing.pem`` (local,
# ``.gitignore``) y en ``secrets.RUNTIME_SIGNING_KEY`` (CI). Si se rota esta
# clave hay que regenerar y publicar un release nuevo del Core — el Android
# side la carga a través de ``assets/runtime/trusted-pubkey.pem`` (copia del
# mismo PEM, inyectada por el gradle task ``:app:packageCoreRuntime``).
EMBEDDED_RUNTIME_PUBLIC_KEY: str = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEARb761DZGp2pTUSFXe9vSyY/k4JmQQhoxvVxy8z6vY4w=
-----END PUBLIC KEY-----
"""


def get_runtime_public_key_pem() -> str:
    """Retorna la clave pública Ed25519 (env var o embebida).

    Prioridad:
        1. Env var ``ORCH_RUNTIME_PUBLIC_KEY`` (tolera escape ``\\n``).
        2. Valor embebido :data:`EMBEDDED_RUNTIME_PUBLIC_KEY`.
    """
    env_key = os.environ.get("ORCH_RUNTIME_PUBLIC_KEY", "").strip()
    if env_key:
        return env_key.replace("\\n", "\n")
    return EMBEDDED_RUNTIME_PUBLIC_KEY


def sign_manifest(manifest: WheelhouseManifest, private_key_pem: str) -> str:
    """Firma el payload canónico del manifest y devuelve hex lowercase.

    Wraps :func:`rove.signing.ed25519.sign_manifest` (que devuelve un
    ``WheelhouseManifest`` con la firma ya inyectada) para preservar la
    API histórica que devuelve sólo el hex de la firma — el caller GIMO
    típico construye el manifest definitivo después con ``model_copy``.

    Raises:
        RuntimeSignatureError: si la clave PEM es inválida o no es Ed25519.
    """
    signed = _rove_sign_manifest(manifest, private_key_pem)
    return signed.signature


def verify_manifest(
    manifest: WheelhouseManifest,
    public_key_pem: Optional[str] = None,
) -> bool:
    """Verifica la firma del manifest contra una clave pública Ed25519.

    Contrato preservado: nunca re-raisea — un fallo de verificación (firma
    inválida, PEM corrupto, clave no configurada) es siempre ``False``.

    Rove's :func:`rove.signing.ed25519.verify_manifest` en cambio *raisea*
    :class:`RuntimeSignatureError` cuando no hay ninguna trusted key en su
    set (env var ``ROVE_TRUSTED_PUBKEYS`` + ``~/.config/rove/trusted_keys/``
    + ``additional_keys``). Como GIMO siempre proveé al menos la clave
    embebida via ``get_runtime_public_key_pem``, la rama "no hay clave"
    sólo se dispara si el usuario explícitamente pasa un PEM vacío — en
    cuyo caso emitimos warning y devolvemos ``False``.
    """
    pem = public_key_pem if public_key_pem is not None else get_runtime_public_key_pem()
    if not pem.strip():
        logger.warning("runtime public key not configured; rejecting manifest")
        return False

    try:
        return _rove_verify_manifest(manifest, additional_keys=(pem,))
    except RuntimeSignatureError as exc:
        logger.warning("runtime verification rejected manifest: %s", exc)
        return False
    except Exception as exc:  # defensivo — cualquier error de crypto = rechazo
        logger.warning("runtime verification raised unexpected error: %s", exc)
        return False


def sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 hex lowercase de un archivo, streaming.

    Delega en :func:`rove.signing.ed25519.sha256_file` pero preserva el
    chunk size histórico de GIMO (1 MiB) — rove por defecto usa 64 KiB,
    aceptable para archivos pequeños pero subóptimo para tarballs de
    50 MB+ donde 1 MiB reduce syscalls ~16×.
    """
    return _rove_sha256_file(Path(path), chunk_size=chunk_size)


__all__ = [
    "EMBEDDED_RUNTIME_PUBLIC_KEY",
    "RuntimeSignatureError",
    "get_runtime_public_key_pem",
    "sha256_file",
    "sign_manifest",
    "verify_manifest",
]
