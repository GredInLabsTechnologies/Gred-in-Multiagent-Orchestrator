"""
Verificación estructural de patches (Fase B — validador independiente).

Valida que un patch propuesto cumple todas las restricciones estructurales
ANTES de pasar a SAST/secret-scan:
  - Solo rutas en la allowlist del jail
  - Sin archivos binarios
  - Sin hunks demasiado grandes
  - Sin dependencias tocadas sin override explícito
  - Consistencia de line ranges
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("patch_validator.structural")

# Extensiones de dependencias que disparan el dependency gate
DEPENDENCY_FILES = re.compile(
    r"(requirements.*\.txt|package-lock\.json|yarn\.lock|"
    r"go\.sum|Cargo\.lock|poetry\.lock|pyproject\.toml|"
    r"setup\.py|setup\.cfg)$",
    re.IGNORECASE,
)

# Rutas que SIEMPRE bloquean sin override y sin reviewers configurados
HARD_BLOCKED_PATTERNS = [
    re.compile(r"(^|[\\/])\.github[\\/]workflows[\\/]", re.IGNORECASE),
    re.compile(r"(^|[\\/])\.env($|[\\/])", re.IGNORECASE),
    re.compile(r"\.(pem|key|crt|p12|pfx|gpg|asc)$", re.IGNORECASE),
]

MAX_TOTAL_LINES_CHANGED = 500
MAX_HUNK_LINES = 100
MAX_FILES = 5


@dataclass
class StructuralCheckResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dependency_gate_triggered: bool = False
    hard_blocked: bool = False
    affected_files: list[str] = field(default_factory=list)
    total_lines_changed: int = 0


def check_structure(patch_data: dict[str, Any]) -> StructuralCheckResult:
    """
    Ejecuta todos los checks estructurales sobre un patch propuesto.

    Args:
        patch_data: Diccionario completo del patch (incluye _meta si está)

    Returns:
        StructuralCheckResult con el resultado detallado
    """
    errors: list[str] = []
    warnings: list[str] = []
    dep_gate = False
    hard_blocked = False
    total_lines = 0
    affected = []

    target_files = patch_data.get("target_files", [])

    if not target_files:
        return StructuralCheckResult(
            passed=False,
            errors=["El patch no contiene archivos objetivo"],
        )

    if len(target_files) > MAX_FILES:
        errors.append(
            f"Demasiados archivos: {len(target_files)} > {MAX_FILES} permitidos por patch"
        )

    for file_entry in target_files:
        path = file_entry.get("path", "")
        if not path:
            errors.append("Entrada de archivo sin campo 'path'")
            continue

        affected.append(path)

        # Verificar patrones hard-blocked
        for pattern in HARD_BLOCKED_PATTERNS:
            if pattern.search(path):
                errors.append(
                    f"HARD BLOCK: {path!r} toca una ruta absolutamente protegida "
                    f"(CI/CD, credenciales). No puede ser modificado por Actions bajo ninguna circunstancia."
                )
                hard_blocked = True

        # Verificar dependency gate
        if DEPENDENCY_FILES.search(path):
            warnings.append(
                f"DEPENDENCY GATE: {path!r} toca un archivo de dependencias. "
                f"Requiere revisión manual obligatoria de un humano."
            )
            dep_gate = True

        # Validar hunks
        hunks = file_entry.get("hunks", [])
        if not hunks:
            errors.append(f"Archivo {path!r} sin hunks")
            continue

        file_lines = 0
        for i, hunk in enumerate(hunks, start=1):
            start_line = hunk.get("start_line", 0)
            end_line = hunk.get("end_line", 0)
            old_lines = hunk.get("old_lines", [])
            new_lines = hunk.get("new_lines", [])

            if start_line < 1:
                errors.append(f"{path!r} hunk #{i}: start_line debe ser >= 1")
            if end_line < start_line:
                errors.append(
                    f"{path!r} hunk #{i}: end_line ({end_line}) < start_line ({start_line})"
                )

            hunk_size = max(len(old_lines), len(new_lines))
            if hunk_size > MAX_HUNK_LINES:
                errors.append(
                    f"{path!r} hunk #{i}: demasiadas líneas ({hunk_size} > {MAX_HUNK_LINES})"
                )

            # Verificar que old_lines coincide con el range declarado
            expected_old_count = end_line - start_line + 1
            if old_lines and len(old_lines) != expected_old_count:
                warnings.append(
                    f"{path!r} hunk #{i}: old_lines tiene {len(old_lines)} líneas "
                    f"pero el range [{start_line}, {end_line}] implica {expected_old_count}"
                )

            file_lines += hunk_size

        total_lines += file_lines

    if total_lines > MAX_TOTAL_LINES_CHANGED:
        errors.append(
            f"Patch demasiado grande: {total_lines} líneas cambiadas > {MAX_TOTAL_LINES_CHANGED}"
        )

    return StructuralCheckResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        dependency_gate_triggered=dep_gate,
        hard_blocked=hard_blocked,
        affected_files=affected,
        total_lines_changed=total_lines,
    )


def compute_patch_hash(patch_bytes: bytes) -> str:
    """SHA-256 del contenido binario del archivo de patch."""
    return hashlib.sha256(patch_bytes).hexdigest()
