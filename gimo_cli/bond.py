"""ServerBond infrastructure — encrypted CLI<->Server connection.

Supports two bond types:
  1. Legacy token bonds (YAML, Fernet-encrypted) — backwards compatible
  2. CLI Bond (AES-256-GCM, hardware fingerprint, JWT) — Identity-First Auth
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from gimo_cli import console
from gimo_cli.config import YAML_AVAILABLE, yaml

logger = logging.getLogger("gimo.bond")

# Ed25519 public key for JWT verification (same as license_guard)
_EMBEDDED_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEApdItyqfVuHkGDXTvzwJrfSSnL3JoXQyWtx8y1hDSA9Y=
-----END PUBLIC KEY-----"""

# AES key derivation salt — distinct from LicenseGuard's salt
_BOND_KEY_SALT = b"GIMO-CLI-BOND-AES-2026-v1"


def gimo_home() -> Path:
    """~/.gimo/ — global GIMO home. Created if missing."""
    home = Path(os.environ.get("GIMO_HOME", str(Path.home() / ".gimo")))
    home.mkdir(parents=True, exist_ok=True)
    return home


def bonds_dir() -> Path:
    """~/.gimo/bonds/ — ServerBond storage."""
    bonds = gimo_home() / "bonds"
    bonds.mkdir(parents=True, exist_ok=True)
    return bonds


def server_fingerprint(url: str) -> str:
    normalized = url.rstrip("/").lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def machine_id() -> str:
    mid_path = gimo_home() / "machine_id"
    if mid_path.exists():
        return mid_path.read_text(encoding="utf-8").strip()
    mid = secrets.token_hex(16)
    mid_path.write_text(mid, encoding="utf-8")
    return mid


# ---------------------------------------------------------------------------
# Hardware fingerprint (reuses server's fingerprint engine if available,
# falls back to machine_id for environments without the server package)
# ---------------------------------------------------------------------------

def _hw_fingerprint() -> str:
    """Generate hardware fingerprint using the server's fingerprint engine."""
    try:
        from tools.gimo_server.security.fingerprint import generate_fingerprint
        return generate_fingerprint()
    except ImportError:
        return hashlib.sha256(machine_id().encode()).hexdigest()


# ---------------------------------------------------------------------------
# AES-256-GCM encryption (machine-bound)
# ---------------------------------------------------------------------------

def _derive_bond_key(fingerprint: str) -> bytes:
    """Derive AES-256 key from hardware fingerprint via PBKDF2.

    Requires the `cryptography` package (same as AES-GCM encryption).
    """
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes as crypto_hashes

    kdf = PBKDF2HMAC(
        algorithm=crypto_hashes.SHA256(),
        length=32,
        salt=_BOND_KEY_SALT,
        iterations=100_000,
    )
    return kdf.derive(fingerprint.encode("utf-8"))


def _aes_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt with AES-256-GCM. Returns nonce(12) + ciphertext+tag."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def _aes_decrypt(data: bytes, key: bytes) -> bytes:
    """Decrypt AES-256-GCM. Raises on tag mismatch (wrong machine)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


# ---------------------------------------------------------------------------
# Legacy token encryption (Fernet, backwards compatible)
# ---------------------------------------------------------------------------

def encrypt_token(token: str) -> str:
    try:
        from cryptography.fernet import Fernet
        machine_fp = machine_id()
        key_material = hashlib.pbkdf2_hmac(
            "sha256", machine_fp.encode(), b"GIMO-BOND-v1", 100_000, dklen=32
        )
        fernet = Fernet(base64.urlsafe_b64encode(key_material))
        return fernet.encrypt(token.encode()).decode()
    except ImportError:
        console.print(
            "[yellow][!] cryptography not available, using base64 obfuscation[/yellow]"
        )
        return base64.b64encode(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    try:
        from cryptography.fernet import Fernet
        machine_fp = machine_id()
        key_material = hashlib.pbkdf2_hmac(
            "sha256", machine_fp.encode(), b"GIMO-BOND-v1", 100_000, dklen=32
        )
        fernet = Fernet(base64.urlsafe_b64encode(key_material))
        return fernet.decrypt(encrypted.encode()).decode()
    except ImportError:
        return base64.b64decode(encrypted.encode()).decode()


# ---------------------------------------------------------------------------
# CLI Bond (Identity-First Auth) — AES-256-GCM + JWT Ed25519
# ---------------------------------------------------------------------------

def _bond_enc_path() -> Path:
    """~/.gimo/bond.enc — the machine-bound CLI bond file."""
    return gimo_home() / "bond.enc"


def save_cli_bond(jwt_token: str, metadata: dict[str, Any] | None = None) -> Path:
    """Save a CLI Bond JWT encrypted with AES-256-GCM using hardware fingerprint.

    The bond file is only decryptable on this machine by this OS user.
    Requires the `cryptography` package.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "CLI Bond requires the 'cryptography' package. "
            "Install with: pip install cryptography"
        )

    fingerprint = _hw_fingerprint()
    key = _derive_bond_key(fingerprint)

    bond_data = {
        "jwt": jwt_token,
        "fingerprint_hash": hashlib.sha256(fingerprint.encode()).hexdigest(),
        "bonded_at": datetime.now(timezone.utc).isoformat(),
        "machine_id": machine_id(),
    }
    if metadata:
        bond_data["metadata"] = metadata

    plaintext = json.dumps(bond_data, separators=(",", ":")).encode("utf-8")
    encrypted = _aes_encrypt(plaintext, key)

    bond_path = _bond_enc_path()
    bond_path.write_bytes(base64.b64encode(encrypted))
    return bond_path


def load_cli_bond() -> dict[str, Any] | None:
    """Load and decrypt the CLI Bond. Returns None if missing/undecryptable."""
    bond_path = _bond_enc_path()
    if not bond_path.exists():
        return None

    try:
        fingerprint = _hw_fingerprint()
        key = _derive_bond_key(fingerprint)
        raw = base64.b64decode(bond_path.read_bytes())
        decrypted = _aes_decrypt(raw, key)
        return json.loads(decrypted.decode("utf-8"))
    except Exception as e:
        logger.debug("CLI Bond load failed (wrong machine or corrupted): %s", e)
        return None


def delete_cli_bond() -> bool:
    """Delete the CLI Bond file."""
    bond_path = _bond_enc_path()
    if bond_path.exists():
        bond_path.unlink()
        return True
    return False


def verify_bond_jwt(jwt_token: str) -> Optional[dict]:
    """Verify a CLI Bond JWT using Ed25519 public key.

    Returns the JWT payload dict or None if verification fails.
    Checks: signature, exp, iat clock-skew.
    """
    public_key_pem = os.environ.get("ORCH_LICENSE_PUBLIC_KEY", "").strip()
    if public_key_pem:
        public_key_pem = public_key_pem.replace("\\n", "\n")
    else:
        public_key_pem = _EMBEDDED_PUBLIC_KEY

    try:
        import jwt as pyjwt
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        public_key = load_pem_public_key(public_key_pem.encode("utf-8"))
        payload = pyjwt.decode(
            jwt_token,
            public_key,  # type: ignore[arg-type]
            algorithms=["EdDSA"],
            options={"verify_exp": True},
        )

        # Anti clock-tampering: system clock cannot be before iat
        now_ts = time.time()
        iat = payload.get("iat", 0)
        if now_ts < iat - 300:
            logger.warning("Bond JWT: clock tampering detected (behind iat)")
            return None

        # Verify scope
        if payload.get("scope") != "cli":
            logger.warning("Bond JWT: invalid scope '%s'", payload.get("scope"))
            return None

        return payload
    except ImportError:
        logger.warning("Bond JWT verification requires PyJWT + cryptography")
        return None
    except Exception as e:
        logger.debug("Bond JWT verification failed: %s", e)
        return None


def resolve_bond_token() -> tuple[str | None, str | None]:
    """Resolve token from CLI Bond (Identity-First Auth).

    Returns (jwt_token, hint_message).
    - If bond exists and valid: (token, None)
    - If bond exists but expired: (None, "Bond expired...")
    - If bond doesn't exist: (None, "Run gimo login...")
    """
    bond = load_cli_bond()
    if not bond:
        return None, None  # No bond — fall through to legacy

    jwt_token = bond.get("jwt")
    if not jwt_token:
        return None, "Bond corrupted. Run: gimo login"

    payload = verify_bond_jwt(jwt_token)
    if payload is None:
        delete_cli_bond()
        return None, "Bond expired or invalid. Run: gimo login"

    return jwt_token, None


# ---------------------------------------------------------------------------
# Legacy ServerBond (YAML-based, backwards compatible)
# ---------------------------------------------------------------------------

def load_bond(server_url: str) -> dict[str, Any] | None:
    if not YAML_AVAILABLE or not yaml:
        return None
    fp = server_fingerprint(server_url)
    bond_path = bonds_dir() / f"{fp}.yaml"
    if not bond_path.exists():
        return None
    try:
        bond = yaml.safe_load(bond_path.read_text(encoding="utf-8"))
        if not isinstance(bond, dict):
            return None
        encrypted = bond.get("token_encrypted")
        if encrypted:
            bond["token"] = decrypt_token(str(encrypted))
        return bond
    except Exception:
        return None


def save_bond(
    server_url: str,
    token: str,
    role: str,
    capabilities: list[str],
    plan: str = "local",
    auth_method: str = "token",
    server_version: str = "unknown",
) -> Path:
    if not YAML_AVAILABLE or not yaml:
        raise RuntimeError("YAML not available, cannot save bond")

    fp = server_fingerprint(server_url)
    bond_path = bonds_dir() / f"{fp}.yaml"

    bond = {
        "server_url": server_url,
        "fingerprint": f"sha256:{fp}",
        "role": role,
        "token_encrypted": encrypt_token(token),
        "bonded_at": datetime.now(timezone.utc).isoformat(),
        "last_verified": datetime.now(timezone.utc).isoformat(),
        "server_version": server_version,
        "auth_method": auth_method,
        "plan": plan,
        "capabilities": capabilities,
    }

    bond_path.write_text(
        yaml.dump(bond, default_flow_style=False), encoding="utf-8"
    )
    return bond_path


def delete_bond(server_url: str) -> bool:
    fp = server_fingerprint(server_url)
    bond_path = bonds_dir() / f"{fp}.yaml"
    if bond_path.exists():
        bond_path.unlink()
        return True
    return False
