"""
GIMO Core Runtime Signature — Ed25519
======================================
Firma y verifica bundles del Core usando la misma infraestructura Ed25519
que ``license_guard.py``. La clave privada vive en CI secrets
(``ORCH_RUNTIME_SIGNING_KEY``); la clave pública viaja embebida en el
producto (bundled) y en env var ``ORCH_RUNTIME_PUBLIC_KEY`` para override.

La firma cubre el payload canónico de :meth:`RuntimeManifest.signing_payload`
— por contrato eso es ``<tarball_sha256>|<target>|<runtime_version>`` UTF-8.
Esto evita ambigüedades de serialización JSON entre productores y consumers
en distintos lenguajes.

Rev 0 — 2026-04-16 (plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING)
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)

from tools.gimo_server.models.runtime import RuntimeManifest

logger = logging.getLogger("orchestrator.runtime_signature")


# Clave pública Ed25519 embebida. Generada con
# ``scripts/generate_runtime_keys.py`` (plan CROSS_COMPILE §Change 5).
# La clave privada asociada vive en ``secrets/runtime-signing.pem`` (local,
# ``.gitignore``) y en ``secrets.RUNTIME_SIGNING_KEY`` (CI). Si se rota esta
# clave hay que regenerar y publicar un release nuevo del Core — el Android
# side la carga a través de ``assets/runtime/trusted-pubkey.pem`` (copia del
# mismo PEM, inyectada por el gradle task ``:app:packageCoreRuntime``).
# Override via env var ``ORCH_RUNTIME_PUBLIC_KEY`` sigue siendo prioritario.
EMBEDDED_RUNTIME_PUBLIC_KEY: str = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEARb761DZGp2pTUSFXe9vSyY/k4JmQQhoxvVxy8z6vY4w=
-----END PUBLIC KEY-----
"""


class RuntimeSignatureError(Exception):
    """Error genérico de firma/verificación del runtime."""


def get_runtime_public_key_pem() -> str:
    """Retorna la clave pública Ed25519 (env var o embebida).

    Prioridad:
        1. Env var ``ORCH_RUNTIME_PUBLIC_KEY`` (tolera escape ``\\n``).
        2. Valor embebido ``EMBEDDED_RUNTIME_PUBLIC_KEY``.
    """
    env_key = os.environ.get("ORCH_RUNTIME_PUBLIC_KEY", "").strip()
    if env_key:
        return env_key.replace("\\n", "\n")
    return EMBEDDED_RUNTIME_PUBLIC_KEY


def _load_private_key(pem: str) -> Ed25519PrivateKey:
    try:
        key = load_pem_private_key(pem.encode("utf-8"), password=None)
    except Exception as exc:  # formato PEM inválido, padding, etc.
        raise RuntimeSignatureError(f"invalid Ed25519 private key PEM: {exc}") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeSignatureError("PEM does not encode an Ed25519 private key")
    return key


def _load_public_key(pem: str) -> Ed25519PublicKey:
    try:
        key = load_pem_public_key(pem.encode("utf-8"))
    except Exception as exc:
        raise RuntimeSignatureError(f"invalid Ed25519 public key PEM: {exc}") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise RuntimeSignatureError("PEM does not encode an Ed25519 public key")
    return key


def sign_manifest(manifest: RuntimeManifest, private_key_pem: str) -> str:
    """Firma el payload canónico del manifest con una clave privada Ed25519.

    Args:
        manifest: manifest validado (sin firma o con firma a sobreescribir).
        private_key_pem: clave privada Ed25519 en PEM PKCS8.

    Returns:
        firma Ed25519 como string hex lowercase de 128 chars (64 bytes).

    Raises:
        RuntimeSignatureError: si la clave PEM es inválida o no es Ed25519.
    """
    priv = _load_private_key(private_key_pem)
    signature_bytes = priv.sign(manifest.signing_payload())
    return signature_bytes.hex()


def verify_manifest(manifest: RuntimeManifest, public_key_pem: Optional[str] = None) -> bool:
    """Verifica la firma del manifest contra una clave pública Ed25519.

    Args:
        manifest: manifest a verificar; usa su propio ``signature`` field.
        public_key_pem: PEM de la clave pública. Si es ``None``, usa
            :func:`get_runtime_public_key_pem`.

    Returns:
        ``True`` si la firma es válida, ``False`` en cualquier otro caso.
        Nunca re-raisea — un fallo de verificación es siempre ``False``,
        nunca una excepción (el caller suele tratarlo como booleano).
    """
    pem = public_key_pem if public_key_pem is not None else get_runtime_public_key_pem()
    if not pem.strip():
        logger.warning("runtime public key not configured; rejecting manifest")
        return False

    try:
        pub = _load_public_key(pem)
    except RuntimeSignatureError as exc:
        logger.warning("public key load failed: %s", exc)
        return False

    try:
        signature_bytes = bytes.fromhex(manifest.signature)
    except ValueError:
        logger.warning("manifest signature is not valid hex")
        return False

    try:
        pub.verify(signature_bytes, manifest.signing_payload())
        return True
    except InvalidSignature:
        return False
    except Exception as exc:  # defensivo — cualquier error de crypto = rechazo
        logger.warning("runtime verification raised unexpected error: %s", exc)
        return False


def sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 hex lowercase de un archivo, streaming en chunks de 1 MiB.

    Usado por el productor ``package_core_runtime.py`` para computar
    ``tarball_sha256`` y por consumers que validan integridad de un payload
    descargado de un peer.

    Args:
        path: ruta absoluta al archivo.
        chunk_size: tamaño del buffer de lectura (default 1 MiB).

    Returns:
        hash SHA-256 como hex string lowercase de 64 chars.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
