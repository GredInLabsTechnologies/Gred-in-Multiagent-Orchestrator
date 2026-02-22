"""
Attestation Ed25519 para el validador de patches.

El validador firma la attestation con su clave privada Ed25519.
El integrador (y el gateway) verifican con la clave pública.

La clave privada NUNCA debe:
  - Estar en el jail de Actions
  - Ser accesible por el usuario del gateway (gimo-actions)
  - Estar en el repositorio (debe estar en un path con ACL estricta)

Formato de attestation (JSON firmado):
    {
        "patch_id":    "<UUID>",
        "patch_hash":  "<SHA-256 del contenido del patch>",
        "policy":      "<versión de política aplicada>",
        "timestamp":   "<ISO-8601 UTC>",
        "checks":      {
            "structural":  "PASS" | "FAIL",
            "sast":        "PASS" | "FAIL" | "SKIP",
            "secrets":     "PASS" | "FAIL",
            "deps":        "PASS" | "FAIL" | "MANUAL_REQUIRED",
        },
        "outcome":     "APPROVED" | "REJECTED" | "MANUAL_REQUIRED",
        "signature":   "<base64url de la firma Ed25519>"
    }

La firma cubre todos los campos EXCEPTO "signature" itself,
usando la serialización JSON canónica (keys ordenadas, sin espacios).
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("patch_validator.attestation")

POLICY_VERSION = "1.0"


def _canonical_json(data: dict[str, Any]) -> bytes:
    """Serialización JSON canónica (sin 'signature')."""
    sans_sig = {k: v for k, v in data.items() if k != "signature"}
    return json.dumps(sans_sig, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


# ------------------------------------------------------------------
# Gestión de claves
# ------------------------------------------------------------------

def generate_keypair(private_key_path: Path, public_key_path: Path) -> None:
    """
    Genera un par de claves Ed25519 y las guarda en PEM.

    Llamar solo una vez durante el setup del sistema.
    La clave privada se guarda con permisos 600.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.parent.mkdir(parents=True, exist_ok=True)

    # Clave privada: sin contraseña, PEM, 600
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_key_path.write_bytes(private_pem)
    try:
        import stat
        private_key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    except Exception:
        logger.warning("No se pudo aplicar chmod 600 a la clave privada (Windows)")

    # Clave pública: PEM, 644
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_path.write_bytes(public_pem)
    logger.info("Par de claves Ed25519 generado en %s / %s", private_key_path, public_key_path)


def _load_private_key(path: Path):
    """Carga la clave privada Ed25519 desde PEM."""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    pem = path.read_bytes()
    return load_pem_private_key(pem, password=None)


def _load_public_key(path: Path):
    """Carga la clave pública Ed25519 desde PEM."""
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    pem = path.read_bytes()
    return load_pem_public_key(pem)


# ------------------------------------------------------------------
# Firma
# ------------------------------------------------------------------

def sign_attestation(
    patch_id: str,
    patch_hash: str,
    checks: dict[str, str],
    outcome: str,
    private_key_path: Path,
) -> dict[str, Any]:
    """
    Crea y firma una attestation para un patch.

    Args:
        patch_id:         UUID del patch
        patch_hash:       SHA-256 del contenido del archivo .json del patch
        checks:           Diccionario de resultados por check
        outcome:          "APPROVED" | "REJECTED" | "MANUAL_REQUIRED"
        private_key_path: Path a la clave privada Ed25519 (solo el validador tiene acceso)

    Returns:
        Diccionario de attestation con signature incluida
    """
    if not private_key_path.exists():
        raise FileNotFoundError(
            f"Clave privada de attestation no encontrada: {private_key_path}\n"
            f"Ejecuta: python -m tools.patch_validator.attestation --generate-keys"
        )

    attestation: dict[str, Any] = {
        "patch_id": patch_id,
        "patch_hash": patch_hash,
        "policy": POLICY_VERSION,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": checks,
        "outcome": outcome,
    }

    canonical = _canonical_json(attestation)

    private_key = _load_private_key(private_key_path)
    raw_sig = private_key.sign(canonical)
    attestation["signature"] = base64.urlsafe_b64encode(raw_sig).decode("ascii")

    logger.info(
        "Attestation firmada: patch_id=%s outcome=%s policy=%s",
        patch_id,
        outcome,
        POLICY_VERSION,
    )
    return attestation


# ------------------------------------------------------------------
# Verificación
# ------------------------------------------------------------------

class AttestationVerificationError(Exception):
    pass


def verify_attestation(attestation: dict[str, Any], public_key_path: Path) -> None:
    """
    Verifica la firma de una attestation.

    Lanza AttestationVerificationError si la firma es inválida o si
    el contenido fue manipulado después de firmar.
    """
    from cryptography.exceptions import InvalidSignature

    if not public_key_path.exists():
        raise AttestationVerificationError(
            f"Clave pública de attestation no encontrada: {public_key_path}"
        )

    sig_b64 = attestation.get("signature", "")
    if not sig_b64:
        raise AttestationVerificationError("Attestation sin campo 'signature'")

    try:
        raw_sig = base64.urlsafe_b64decode(sig_b64 + "==")
    except Exception as exc:
        raise AttestationVerificationError(f"Firma base64 inválida: {exc}")

    canonical = _canonical_json(attestation)

    try:
        public_key = _load_public_key(public_key_path)
        public_key.verify(raw_sig, canonical)
    except InvalidSignature:
        raise AttestationVerificationError(
            "Firma Ed25519 INVÁLIDA — la attestation fue manipulada o proviene de una clave distinta"
        )
    except Exception as exc:
        raise AttestationVerificationError(f"Error al verificar firma: {exc}")

    logger.info(
        "Attestation verificada: patch_id=%s outcome=%s policy=%s",
        attestation.get("patch_id"),
        attestation.get("outcome"),
        attestation.get("policy"),
    )


# ------------------------------------------------------------------
# CLI para generación de claves
# ------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Herramienta de attestation para patch_validator")
    parser.add_argument(
        "--generate-keys",
        action="store_true",
        help="Generar par de claves Ed25519 para attestation",
    )
    parser.add_argument(
        "--private-key",
        default="tools/patch_validator/keys/attestation_private.pem",
        help="Path para la clave privada",
    )
    parser.add_argument(
        "--public-key",
        default="tools/patch_validator/keys/attestation_public.pem",
        help="Path para la clave pública",
    )
    args = parser.parse_args()

    if args.generate_keys:
        priv = Path(args.private_key)
        pub = Path(args.public_key)
        if priv.exists() or pub.exists():
            confirm = input(
                f"¡ATENCIÓN! Ya existen claves en {priv} / {pub}. "
                f"Regenerar las claves invalida todas las attestations existentes. "
                f"¿Continuar? (escribe 'SI' para confirmar): "
            )
            if confirm.strip() != "SI":
                print("Operación cancelada.")
                raise SystemExit(0)
        generate_keypair(priv, pub)
        print(f"Claves generadas:\n  Privada: {priv}\n  Pública: {pub}")
        print(f"\n⚠️  IMPORTANTE: Asegura la clave privada con ACL estricta:")
        print(f"  icacls {priv} /inheritance:r /grant:r \"<validator-user>:(R)\"")
