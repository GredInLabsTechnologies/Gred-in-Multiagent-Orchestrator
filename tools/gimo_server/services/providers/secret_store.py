"""AES-256-GCM encrypted vault for provider API keys.

Reuses the same PBKDF2 + hardware-fingerprint key derivation as
license_guard.py. Different salt prevents key reuse across subsystems.

File: .orch_data/ops/state/provider_secrets.enc
Format: base64(nonce(12) || AES-GCM ciphertext of JSON dict)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import stat
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orchestrator.secret_store")

_SALT = b"GIMO-PROVIDER-SECRETS-2026-v1"
_STORE_REL = Path(".orch_data") / "ops" / "state" / "provider_secrets.enc"


def _derive_key() -> bytes:
    from ...security.fingerprint import generate_fingerprint
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=100_000,
    )
    return kdf.derive(generate_fingerprint().encode("utf-8"))


def _store_path() -> Path:
    return Path.cwd() / _STORE_REL


def load_secrets() -> dict[str, str]:
    """Read and decrypt all secrets. Returns {} if file missing or corrupt."""
    path = _store_path()
    if not path.exists():
        return {}
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        raw = base64.b64decode(path.read_bytes())
        nonce, ct = raw[:12], raw[12:]
        plaintext = AESGCM(_derive_key()).decrypt(nonce, ct, None)
        return json.loads(plaintext)
    except Exception:
        logger.warning("Secret store corrupt or unreadable; treating as empty")
        return {}


def save_secrets(secrets: dict[str, str]) -> None:
    """Encrypt and write all secrets atomically."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    nonce = os.urandom(12)
    ct = AESGCM(_derive_key()).encrypt(nonce, json.dumps(secrets).encode("utf-8"), None)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(base64.b64encode(nonce + ct))
    tmp.replace(path)  # Atomic rename
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600 — best-effort on Windows
    except OSError:
        pass


def get_secret(env_name: str) -> Optional[str]:
    """Read a single secret by env var name."""
    logger.debug("Secret read: %s", env_name)
    return load_secrets().get(env_name)


def set_secret(env_name: str, value: str) -> None:
    """Store a single secret (creates or overwrites)."""
    secrets = load_secrets()
    secrets[env_name] = value
    save_secrets(secrets)
    logger.info("Secret stored: %s", env_name)


def delete_secret(env_name: str) -> bool:
    """Remove a single secret. Returns True if it existed."""
    secrets = load_secrets()
    if env_name not in secrets:
        return False
    del secrets[env_name]
    save_secrets(secrets)
    logger.info("Secret deleted: %s", env_name)
    return True
