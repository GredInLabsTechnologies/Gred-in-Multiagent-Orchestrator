"""ServerBond infrastructure — encrypted CLI<->Server connection."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gimo_cli import console
from gimo_cli.config import YAML_AVAILABLE, yaml


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


def encrypt_token(token: str) -> str:
    try:
        from cryptography.fernet import Fernet
        import base64
        machine_fp = machine_id()
        key_material = hashlib.pbkdf2_hmac("sha256", machine_fp.encode(), b"GIMO-BOND-v1", 100_000, dklen=32)
        fernet = Fernet(base64.urlsafe_b64encode(key_material))
        return fernet.encrypt(token.encode()).decode()
    except ImportError:
        import base64
        console.print("[yellow][!] cryptography not available, using base64 obfuscation (install cryptography for AES-256-GCM)[/yellow]")
        return base64.b64encode(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    try:
        from cryptography.fernet import Fernet
        import base64
        machine_fp = machine_id()
        key_material = hashlib.pbkdf2_hmac("sha256", machine_fp.encode(), b"GIMO-BOND-v1", 100_000, dklen=32)
        fernet = Fernet(base64.urlsafe_b64encode(key_material))
        return fernet.decrypt(encrypted.encode()).decode()
    except ImportError:
        import base64
        return base64.b64decode(encrypted.encode()).decode()


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

    bond_path.write_text(yaml.dump(bond, default_flow_style=False), encoding="utf-8")
    return bond_path


def delete_bond(server_url: str) -> bool:
    fp = server_fingerprint(server_url)
    bond_path = bonds_dir() / f"{fp}.yaml"
    if bond_path.exists():
        bond_path.unlink()
        return True
    return False
