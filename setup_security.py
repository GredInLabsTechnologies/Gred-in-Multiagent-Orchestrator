#!/usr/bin/env python3
"""
Genera un manifest simple de integridad para archivos críticos de GIMO.

Uso:
    python setup_security.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key


CRITICAL_FILES = [
    "tools/gimo_server/main.py",
    "tools/gimo_server/config.py",
    "tools/gimo_server/security/license_guard.py",
    "tools/gimo_server/security/cold_room.py",
    "tools/gimo_server/security/runtime_guard.py",
    "tools/gimo_server/security/integrity.py",
]


def _sha256_normalized(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def generate_manifest(repo_root: Path) -> dict:
    files: dict[str, str] = {}
    for rel in CRITICAL_FILES:
        abs_path = (repo_root / rel).resolve()
        if not abs_path.exists() or not abs_path.is_file():
            continue
        files[rel] = _sha256_normalized(abs_path)

    return {
        "v": 1,
        "files": files,
    }


def _load_private_key_from_env() -> Ed25519PrivateKey | None:
    pem = os.environ.get("ORCH_INTEGRITY_PRIVATE_KEY", "").strip()
    if not pem:
        return None
    normalized = pem.replace("\\n", "\n").encode("utf-8")
    loaded = load_pem_private_key(normalized, password=None)
    if not isinstance(loaded, Ed25519PrivateKey):
        raise TypeError("ORCH_INTEGRITY_PRIVATE_KEY no es una clave Ed25519 válida")
    return loaded


def _sign_manifest(manifest: dict, private_key: Ed25519PrivateKey | None) -> dict:
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if private_key is None:
        return {
            "manifest": manifest,
            "signature": "",
        }
    signature = private_key.sign(manifest_bytes)
    return {
        "manifest": manifest,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parent
    manifest = generate_manifest(repo_root)
    private_key = _load_private_key_from_env()
    payload = _sign_manifest(manifest, private_key)
    out_path = repo_root / ".gimo_manifest"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    signed_msg = "firmado" if private_key is not None else "NO firmado (modo dev)"
    print(f"Manifest {signed_msg}: {out_path} ({len(manifest['files'])} archivos)")


if __name__ == "__main__":
    main()
