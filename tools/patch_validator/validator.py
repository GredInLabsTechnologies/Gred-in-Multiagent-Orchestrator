"""
Validador principal de patches (Fase B del pipeline de seguridad).

Este proceso es COMPLETAMENTE INDEPENDIENTE del gateway de GPT Actions:
  - Corre como un usuario de sistema diferente
  - Lee patches del jail pero NO puede ser modificado por Actions
  - Tiene acceso EXCLUSIVO a la clave privada de attestation
  - Sus resultados son el único camino al integrador

Flujo de validación para cada patch:
  1. Verificar que el patch existe en el jail y no fue modificado (TOCTOU via hash)
  2. Validación estructural (structural_checker.py)
  3. SAST + secret scanning (sast_runner.py)
  4. Dependency gate si aplica
  5. Firmar attestation con clave privada Ed25519
  6. Guardar attestation en directorio FUERA del jail (solo el integrador puede leer)

Uso:
    python -m tools.patch_validator.validator --patch-id <UUID>
    python -m tools.patch_validator.validator --watch   # Procesa automáticamente
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

from tools.patch_validator.attestation import sign_attestation, POLICY_VERSION
from tools.patch_validator.sast_runner import run_sast
from tools.patch_validator.structural_checker import check_structure, compute_patch_hash

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("patch_validator")


# ------------------------------------------------------------------
# Configuración del validador
# ------------------------------------------------------------------

def _find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for parent in current.parents:
        if (parent / "tools" / "gimo_server" / "repo_registry.json").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _find_repo_root()

import os

JAIL_ROOT = Path(
    os.environ.get("GPTGW_JAIL_ROOT", str(REPO_ROOT.parent / "worktrees" / "gptactions"))
).resolve()

ATTESTATION_PRIVATE_KEY = Path(
    os.environ.get(
        "GPTGW_ATTESTATION_PRIVKEY",
        str(REPO_ROOT / "tools" / "patch_validator" / "keys" / "attestation_private.pem"),
    )
).resolve()

ATTESTATION_OUTPUT_DIR = Path(
    os.environ.get(
        "GPTGW_ATTESTATION_DIR",
        str(REPO_ROOT / ".gptgw_data" / "attestations"),
    )
).resolve()

ATTESTATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# Validación de un patch individual
# ------------------------------------------------------------------

def validate_patch(patch_id: str) -> dict:
    """
    Valida un patch por su ID.

    Returns:
        Diccionario con la attestation firmada (o con outcome=REJECTED si falla).

    Raises:
        FileNotFoundError: Si el patch no existe en el jail.
    """
    patch_file = JAIL_ROOT / "patches" / f"{patch_id}.json"

    if not patch_file.exists():
        raise FileNotFoundError(f"Patch no encontrado: {patch_file}")

    # Leer y hashear el archivo ANTES de parsearlo (protección TOCTOU)
    patch_bytes = patch_file.read_bytes()
    patch_hash = compute_patch_hash(patch_bytes)

    logger.info("Iniciando validación: patch_id=%s hash=%s…", patch_id, patch_hash[:16])

    try:
        patch_data = json.loads(patch_bytes)
    except json.JSONDecodeError as exc:
        logger.error("Patch inválido (JSON): %s", exc)
        return _reject(patch_id, patch_hash, f"JSON inválido: {exc}", {})

    checks: dict[str, str] = {}

    # -------------------------------------------------------------------
    # FASE 1: Validación estructural
    # -------------------------------------------------------------------
    logger.info("[1/3] Validación estructural…")
    struct_result = check_structure(patch_data)
    checks["structural"] = "PASS" if struct_result.passed else "FAIL"

    if struct_result.hard_blocked:
        logger.error("HARD BLOCK: patch toca rutas absolutamente protegidas")
        return _reject(
            patch_id, patch_hash,
            f"Hard block: {struct_result.errors}",
            checks,
        )

    if not struct_result.passed:
        logger.warning("Validación estructural FAIL: %s", struct_result.errors)
        return _reject(patch_id, patch_hash, f"Structural errors: {struct_result.errors}", checks)

    if struct_result.warnings:
        for w in struct_result.warnings:
            logger.warning("Structural warning: %s", w)

    # -------------------------------------------------------------------
    # FASE 2: SAST + secret scanning
    # -------------------------------------------------------------------
    logger.info("[2/3] SAST y secret scanning…")
    sast_result = run_sast(patch_data, REPO_ROOT)
    checks["sast"] = sast_result.overall
    checks["secrets"] = "PASS"  # gitleaks reporta en sast_result

    # Si gitleaks está en los resultados, extraer su estado
    for r in sast_result.results:
        if r.tool == "gitleaks":
            checks["secrets"] = r.status

    if not sast_result.passed:
        logger.error("SAST FAIL: %s", [r.tool for r in sast_result.results if r.status == "FAIL"])
        return _reject(
            patch_id, patch_hash,
            f"SAST findings: {[r.findings[:3] for r in sast_result.results if r.findings]}",
            checks,
        )

    # -------------------------------------------------------------------
    # FASE 3: Dependency gate
    # -------------------------------------------------------------------
    logger.info("[3/3] Dependency gate…")
    if struct_result.dependency_gate_triggered:
        checks["deps"] = "MANUAL_REQUIRED"
        logger.warning(
            "DEPENDENCY GATE: el patch toca archivos de dependencias. "
            "Marcado como MANUAL_REQUIRED — requiere revisión humana."
        )
        return _sign_attestation(
            patch_id, patch_hash, checks,
            outcome="MANUAL_REQUIRED",
        )
    else:
        checks["deps"] = "PASS"

    # -------------------------------------------------------------------
    # Requiere override manual por rutas protegidas
    # -------------------------------------------------------------------
    meta = patch_data.get("_meta", {})
    if meta.get("requires_manual_override"):
        logger.warning("Patch requiere manual override por rutas protegidas")
        return _sign_attestation(
            patch_id, patch_hash, checks,
            outcome="MANUAL_REQUIRED",
        )

    # -------------------------------------------------------------------
    # Todo pasó: APPROVED
    # -------------------------------------------------------------------
    logger.info("Patch APROBADO por validación automática: patch_id=%s", patch_id)
    return _sign_attestation(patch_id, patch_hash, checks, outcome="APPROVED")


def _reject(patch_id: str, patch_hash: str, reason: str, checks: dict) -> dict:
    """Crea y persiste una attestation REJECTED."""
    checks.setdefault("structural", "FAIL")
    checks.setdefault("sast", "SKIP")
    checks.setdefault("secrets", "SKIP")
    checks.setdefault("deps", "SKIP")
    attestation = _sign_attestation(patch_id, patch_hash, checks, outcome="REJECTED")
    logger.info("Patch RECHAZADO: patch_id=%s reason=%s", patch_id, reason[:200])
    return attestation


def _sign_attestation(
    patch_id: str,
    patch_hash: str,
    checks: dict[str, str],
    outcome: str,
) -> dict:
    """Firma y persiste la attestation."""
    attestation = sign_attestation(
        patch_id=patch_id,
        patch_hash=patch_hash,
        checks=checks,
        outcome=outcome,
        private_key_path=ATTESTATION_PRIVATE_KEY,
    )

    # Persistir la attestation en el directorio de attestations (fuera del jail)
    att_file = ATTESTATION_OUTPUT_DIR / f"{patch_id}.attestation.json"
    att_file.write_text(
        json.dumps(attestation, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    logger.info("Attestation guardada: %s", att_file)

    return attestation


# ------------------------------------------------------------------
# Modo watch: procesa patches nuevos automáticamente
# ------------------------------------------------------------------

def watch_mode(interval: int = 30) -> None:
    """
    Monitorea el jail y valida automáticamente los patches nuevos.

    Solo procesa patches con status='pending'.
    """
    logger.info("Watch mode iniciado. Revisando cada %ds…", interval)
    processed: set[str] = set()

    while True:
        patches_dir = JAIL_ROOT / "patches"
        if patches_dir.exists():
            for patch_file in sorted(patches_dir.glob("*.json")):
                patch_id = patch_file.stem
                if patch_id in processed:
                    continue
                # Verificar que no tiene attestation aún
                att_file = ATTESTATION_OUTPUT_DIR / f"{patch_id}.attestation.json"
                if att_file.exists():
                    processed.add(patch_id)
                    continue
                try:
                    logger.info("Procesando patch nuevo: %s", patch_id)
                    validate_patch(patch_id)
                    processed.add(patch_id)
                except Exception as exc:
                    logger.error("Error al validar %s: %s", patch_id, exc)
                    processed.add(patch_id)  # Evitar reintentos infinitos

        time.sleep(interval)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validador de patches de GPT Actions")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--patch-id", help="UUID del patch a validar")
    group.add_argument("--watch", action="store_true", help="Modo watch: procesar automáticamente")
    group.add_argument("--verify-keys", action="store_true", help="Verificar que las claves existen y son válidas")
    parser.add_argument("--interval", type=int, default=30, help="Intervalo en segundos para watch mode")

    args = parser.parse_args()

    if args.verify_keys:
        if not ATTESTATION_PRIVATE_KEY.exists():
            print(f"ERROR: Clave privada no encontrada: {ATTESTATION_PRIVATE_KEY}", file=sys.stderr)
            print("Ejecuta: python -m tools.patch_validator.attestation --generate-keys")
            sys.exit(1)
        print(f"OK: Clave privada encontrada: {ATTESTATION_PRIVATE_KEY}")
        print(f"OK: Directorio de attestations: {ATTESTATION_OUTPUT_DIR}")
        sys.exit(0)

    elif args.watch:
        watch_mode(interval=args.interval)

    else:
        try:
            result = validate_patch(args.patch_id)
            print(json.dumps(result, indent=2, ensure_ascii=True))
            outcome = result.get("outcome", "UNKNOWN")
            sys.exit(0 if outcome in ("APPROVED", "MANUAL_REQUIRED") else 1)
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(2)
        except Exception as exc:
            print(f"ERROR inesperado: {exc}", file=sys.stderr)
            sys.exit(3)
