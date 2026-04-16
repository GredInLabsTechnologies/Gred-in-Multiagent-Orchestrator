#!/usr/bin/env python3
"""
GIMO Runtime Signing — Keypair generator
=========================================
Genera un keypair Ed25519 para firmar bundles del Core GIMO producidos por
``scripts/package_core_runtime.py``. Sigue el mismo patrón que
``scripts/generate_license_keys.py`` (mantiene paridad operativa entre
license_guard y runtime_signature).

Uso típico — flujo release:

    python scripts/generate_runtime_keys.py \\
        --out-priv secrets/runtime-signing.pem \\
        --out-pub runtime-assets/trusted-pubkey.pem

Luego:
    1. Subir el PEM privado a GitHub Secrets (``RUNTIME_SIGNING_KEY``).
    2. Embeber el PEM público en ``tools/gimo_server/security/runtime_signature.py``
       (constante ``EMBEDDED_RUNTIME_PUBLIC_KEY``).
    3. Commit del PEM público (es público por diseño — no secreto).
    4. El PEM privado NO se commitea (``secrets/`` está en ``.gitignore``).

Plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_CROSS_COMPILE §Change 5.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def generate_keypair() -> tuple[str, str]:
    """Genera un Ed25519 keypair y retorna (priv_pem, pub_pem)."""
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode("utf-8")
    pub_pem = priv.public_key().public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate_runtime_keys")
    parser.add_argument("--out-priv", required=True, help="Output path for private key PEM")
    parser.add_argument("--out-pub", required=True, help="Output path for public key PEM")
    args = parser.parse_args(argv)

    priv_pem, pub_pem = generate_keypair()

    priv_path = Path(args.out_priv)
    pub_path = Path(args.out_pub)
    priv_path.parent.mkdir(parents=True, exist_ok=True)
    pub_path.parent.mkdir(parents=True, exist_ok=True)
    priv_path.write_text(priv_pem, encoding="utf-8")
    pub_path.write_text(pub_pem, encoding="utf-8")

    # Restrict permissions on the private key (best-effort, ignored on Windows).
    try:
        priv_path.chmod(0o600)
    except Exception:  # noqa: BLE001
        pass

    print(f"private key -> {priv_path}")
    print(f"public  key -> {pub_path}")
    print()
    print("Embed this public key in runtime_signature.py:")
    print()
    print('EMBEDDED_RUNTIME_PUBLIC_KEY = """' + pub_pem.strip() + '"""')
    return 0


if __name__ == "__main__":
    sys.exit(main())
