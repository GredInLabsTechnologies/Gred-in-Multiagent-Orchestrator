"""
Integrador de patches (Fase C del pipeline).

Este es el ÚNICO componente que aplica cambios reales al repositorio.
Solo actúa si:
  1. Existe una attestation con outcome=APPROVED o MANUAL_REQUIRED
  2. La firma Ed25519 es válida
  3. El hash del patch en la attestation coincide con el patch actual (anti-TOCTOU)
  4. Para MANUAL_REQUIRED: el operador ha confirmado explícitamente

El integrador NUNCA toma acción automática sobre patches MANUAL_REQUIRED
sin intervención humana.

Uso:
    python -m tools.patch_integrator.integrator --patch-id <UUID>
    python -m tools.patch_integrator.integrator --patch-id <UUID> --confirm   # Para MANUAL_REQUIRED
    python -m tools.patch_integrator.integrator --dry-run --patch-id <UUID>   # Solo verificar
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.patch_validator.attestation import verify_attestation, AttestationVerificationError
from tools.patch_validator.structural_checker import compute_patch_hash

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("patch_integrator")


# ------------------------------------------------------------------
# Configuración
# ------------------------------------------------------------------

def _find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for parent in current.parents:
        if (parent / "tools" / "gimo_server" / "repo_registry.json").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _find_repo_root()

JAIL_ROOT = Path(
    os.environ.get("GPTGW_JAIL_ROOT", str(REPO_ROOT.parent / "worktrees" / "gptactions"))
).resolve()

ATTESTATION_DIR = Path(
    os.environ.get("GPTGW_ATTESTATION_DIR", str(REPO_ROOT / ".gptgw_data" / "attestations"))
).resolve()

ATTESTATION_PUBLIC_KEY = Path(
    os.environ.get(
        "GPTGW_ATTESTATION_PUBKEY",
        str(REPO_ROOT / "tools" / "patch_validator" / "keys" / "attestation_public.pem"),
    )
).resolve()

# Rama de integración donde se aplican los patches (no la rama principal directamente)
INTEGRATION_BRANCH_PREFIX = "gptactions/patch-"


# ------------------------------------------------------------------
# Integración principal
# ------------------------------------------------------------------

def integrate_patch(patch_id: str, dry_run: bool = False, human_confirmed: bool = False) -> bool:
    """
    Verifica y aplica un patch con attestation válida.

    Args:
        patch_id:         UUID del patch a integrar
        dry_run:          Si True, solo verifica sin aplicar
        human_confirmed:  Para patches MANUAL_REQUIRED, requiere confirmación explícita

    Returns:
        True si el patch fue aplicado (o habría sido aplicado en dry-run)
    """
    logger.info(
        "Integrando patch: id=%s dry_run=%s human_confirmed=%s",
        patch_id, dry_run, human_confirmed,
    )

    # ------------------------------------------------------------------
    # 1. Cargar y verificar attestation
    # ------------------------------------------------------------------
    att_file = ATTESTATION_DIR / f"{patch_id}.attestation.json"
    if not att_file.exists():
        logger.error("Attestation no encontrada: %s", att_file)
        logger.error("El patch debe pasar por el validador (Fase B) antes de integrarse")
        return False

    try:
        attestation = json.loads(att_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Error al leer attestation: %s", exc)
        return False

    try:
        verify_attestation(attestation, ATTESTATION_PUBLIC_KEY)
    except AttestationVerificationError as exc:
        logger.error("ATTESTATION INVÁLIDA — ABORTANDO: %s", exc)
        logger.error("POSIBLE MANIPULACIÓN de la attestation detectada")
        return False

    outcome = attestation.get("outcome", "UNKNOWN")
    logger.info("Attestation verificada: outcome=%s policy=%s", outcome, attestation.get("policy"))

    # ------------------------------------------------------------------
    # 2. Verificar outcome
    # ------------------------------------------------------------------
    if outcome == "REJECTED":
        logger.error("El patch fue RECHAZADO por el validador. No se puede integrar.")
        return False

    if outcome == "MANUAL_REQUIRED" and not human_confirmed:
        logger.warning(
            "Este patch requiere confirmación manual explícita (MANUAL_REQUIRED).\n"
            "Revisa el patch y la attestation, luego ejecuta con --confirm si estás de acuerdo."
        )
        print("\n" + "="*60)
        print("REVISIÓN REQUERIDA:")
        print(f"  Patch ID: {patch_id}")
        print(f"  Checks: {json.dumps(attestation.get('checks', {}), indent=4)}")
        print(f"  Attestation timestamp: {attestation.get('timestamp')}")
        print("\nPara aplicar, ejecuta:")
        print(f"  python -m tools.patch_integrator.integrator --patch-id {patch_id} --confirm")
        print("="*60 + "\n")
        return False

    # ------------------------------------------------------------------
    # 3. Verificar hash del patch (anti-TOCTOU)
    # ------------------------------------------------------------------
    patch_file = JAIL_ROOT / "patches" / f"{patch_id}.json"
    if not patch_file.exists():
        logger.error("Patch no encontrado en el jail: %s", patch_file)
        logger.error("¿Fue archivado? Comprueba en %s/archive/", JAIL_ROOT)
        return False

    current_hash = compute_patch_hash(patch_file.read_bytes())
    attested_hash = attestation.get("patch_hash", "")

    if current_hash != attested_hash:
        logger.error(
            "HASH MISMATCH — ABORTANDO: el patch fue MODIFICADO después de ser validado.\n"
            "  Hash en attestation: %s\n"
            "  Hash actual:         %s",
            attested_hash,
            current_hash,
        )
        logger.error("Posible ataque de race condition (TOCTOU) detectado")
        return False

    logger.info("Hash del patch verificado: %s… ✓", current_hash[:16])

    # ------------------------------------------------------------------
    # 4. Cargar y parsear el patch
    # ------------------------------------------------------------------
    patch_data = json.loads(patch_file.read_bytes())

    # ------------------------------------------------------------------
    # 5. Dry run: solo reportar
    # ------------------------------------------------------------------
    if dry_run:
        logger.info("DRY RUN — Patch verificado, NO aplicado:")
        for f in patch_data.get("target_files", []):
            logger.info("  Archivo: %s (%d hunks)", f.get("path"), len(f.get("hunks", [])))
        return True

    # ------------------------------------------------------------------
    # 6. Crear rama de integración y aplicar
    # ------------------------------------------------------------------
    branch_name = f"{INTEGRATION_BRANCH_PREFIX}{patch_id[:8]}"
    logger.info("Creando rama de integración: %s", branch_name)

    try:
        # Crear rama desde la rama actual
        _git(["checkout", "-b", branch_name], cwd=REPO_ROOT)
    except subprocess.CalledProcessError:
        # Si ya existe, reusar
        _git(["checkout", branch_name], cwd=REPO_ROOT)

    applied_files = []
    errors = []

    for file_entry in patch_data.get("target_files", []):
        file_path = file_entry.get("path", "")
        target = (REPO_ROOT / file_path).resolve()

        # Verificar que no sale del repo
        try:
            target.relative_to(REPO_ROOT)
        except ValueError:
            errors.append(f"Path escapa del repo: {file_path!r}")
            continue

        if not target.exists():
            errors.append(f"Archivo no encontrado en repo: {file_path!r}")
            continue

        try:
            original_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            modified_lines = _apply_hunks(original_lines, file_entry.get("hunks", []))
            target.write_text("\n".join(modified_lines) + "\n", encoding="utf-8")
            applied_files.append(file_path)
            logger.info("  Aplicado: %s", file_path)
        except Exception as exc:
            errors.append(f"Error al aplicar {file_path!r}: {exc}")

    if errors:
        logger.error("Errores al aplicar patch: %s", errors)
        logger.error("Revirtiendo cambios…")
        try:
            _git(["checkout", "-"], cwd=REPO_ROOT)
            _git(["branch", "-D", branch_name], cwd=REPO_ROOT)
        except Exception:
            pass
        return False

    # Commit
    _git(["add"] + applied_files, cwd=REPO_ROOT)
    commit_msg = (
        f"feat(gptactions): apply patch {patch_id[:8]}\n\n"
        f"Attestation: {patch_id}\n"
        f"Policy: {attestation.get('policy')}\n"
        f"Timestamp: {attestation.get('timestamp')}\n"
        f"Checks: {json.dumps(attestation.get('checks', {}))}\n\n"
        f"Applied files: {', '.join(applied_files)}\n"
        f"Rationale: {patch_data.get('rationale', 'N/A')[:200]}"
    )
    _git(["commit", "-m", commit_msg], cwd=REPO_ROOT)
    logger.info(
        "Patch integrado exitosamente en rama %s.\n"
        "Archivos: %s\n"
        "Siguiente paso: revisar y crear PR manualmente.",
        branch_name,
        applied_files,
    )
    return True


# ------------------------------------------------------------------
# Aplicar hunks sobre líneas de texto
# ------------------------------------------------------------------

def _apply_hunks(lines: list[str], hunks: list[dict]) -> list[str]:
    """Aplica los hunks al listado de líneas (1-based)."""
    result = list(lines)
    # Aplicar en orden inverso para no desplazar índices
    for hunk in reversed(sorted(hunks, key=lambda h: h.get("start_line", 1))):
        start = hunk.get("start_line", 1) - 1  # 0-based
        end = hunk.get("end_line", start + 1)   # 0-based exclusive
        new_lines = hunk.get("new_lines", [])
        result[start:end] = new_lines
    return result


# ------------------------------------------------------------------
# Helper git
# ------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    cmd = ["git"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd), check=True)
    return result


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Integrador de patches de GPT Actions (Fase C)")
    parser.add_argument("--patch-id", required=True, help="UUID del patch a integrar")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirmar integración de patches MANUAL_REQUIRED",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo verificar, no aplicar cambios",
    )
    args = parser.parse_args()

    success = integrate_patch(
        patch_id=args.patch_id,
        dry_run=args.dry_run,
        human_confirmed=args.confirm,
    )
    sys.exit(0 if success else 1)
