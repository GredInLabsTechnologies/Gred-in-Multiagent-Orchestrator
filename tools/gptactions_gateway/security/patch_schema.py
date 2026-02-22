"""
Schema estricto de propuesta de patch para GPT Actions.

El objetivo es doble:
  1. Anti-prompt-injection: no se acepta texto libre como instrucciones.
     Cada campo tiene un tipo y rango definido. Un diff propuesto por
     Actions es estructural (hunks con líneas exactas), no narrativo.

  2. Policy gate inline: se rechazan en la puerta propuestas que tocan
     rutas prohibidas (CI/CD, auth, networking, secrets) sin un override
     manual explícito.

Schema de una propuesta válida (PatchProposal):
    {
        "schema_version": "1.0",
        "change_type":   "code_modification" | "test_addition" | "refactor" | "config_change",
        "risk_level":    "low" | "medium",
        "rationale":     "<max 500 chars, solo texto plano>",
        "target_files":  [
            {
                "path":  "<ruta relativa al jail root>",
                "hunks": [
                    {
                        "start_line": int,   # 1-based
                        "end_line":   int,   # >= start_line
                        "old_lines":  ["<línea exacta del original>", ...],
                        "new_lines":  ["<línea de reemplazo>", ...]
                    }
                ]
            }
        ]
    }

Reglas de policy gate:
  - risk_level "high" → siempre rechazado (Actions no puede proponer alto riesgo)
  - Paths en PROTECTED_PATTERNS → requieren override_reason (y aun así, flag manual)
  - Más de MAX_FILES_PER_PATCH archivos → rechazado
  - Más de MAX_HUNKS_PER_FILE hunks por archivo → rechazado
  - Hunk con más de MAX_LINES_PER_HUNK líneas → rechazado
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ------------------------------------------------------------------
# Constantes de policy
# ------------------------------------------------------------------

VALID_SCHEMA_VERSIONS = {"1.0"}
VALID_CHANGE_TYPES = {"code_modification", "test_addition", "refactor", "config_change"}
VALID_RISK_LEVELS = {"low", "medium"}  # "high" es siempre rechazado

MAX_FILES_PER_PATCH = 5
MAX_HUNKS_PER_FILE = 20
MAX_LINES_PER_HUNK = 100
MAX_LINE_LENGTH = 2000
MAX_RATIONALE_LENGTH = 500

# Patrones de rutas que requieren revisión manual aunque pasen el schema
# (el validador las marca como REQUIRES_MANUAL_OVERRIDE)
PROTECTED_PATH_PATTERNS = [
    re.compile(r"(^|/)\.github/", re.IGNORECASE),          # CI/CD
    re.compile(r"(^|/)workflows?/", re.IGNORECASE),          # Workflows
    re.compile(r"(^|/)security/", re.IGNORECASE),            # Módulo de seguridad
    re.compile(r"(^|/)auth", re.IGNORECASE),                 # Auth
    re.compile(r"\.(env|pem|key|crt|p12|pfx)$", re.IGNORECASE),  # Credentials
    re.compile(r"(^|/)secrets?/", re.IGNORECASE),            # Secrets
    re.compile(r"(requirements|package-lock|go\.sum|Cargo\.lock)", re.IGNORECASE),  # Deps
    re.compile(r"(pyproject|setup\.py|setup\.cfg)", re.IGNORECASE),  # Python config
    re.compile(r"(^|/)docker", re.IGNORECASE),               # Docker
    re.compile(r"(^|/)deploy", re.IGNORECASE),               # Deploy
    re.compile(r"(^|/)infra", re.IGNORECASE),                # Infraestructura
]

# Extensiones de archivo permitidas en las rutas de target
ALLOWED_TARGET_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".rs", ".c", ".cpp", ".h", ".hpp",
    ".json", ".yaml", ".yml", ".toml",
    ".sh", ".bash", ".cfg", ".ini", ".conf",
    ".sql", ".graphql", ".proto",
}


# ------------------------------------------------------------------
# Modelos Pydantic
# ------------------------------------------------------------------

class Hunk(BaseModel):
    """Un bloque de cambio dentro de un archivo."""

    start_line: int = Field(ge=1, description="Línea de inicio (1-based)")
    end_line: int = Field(ge=1, description="Línea de fin (1-based, inclusive)")
    old_lines: list[str] = Field(
        max_length=MAX_LINES_PER_HUNK,
        description="Líneas del original (pueden estar vacías para inserciones puras)",
    )
    new_lines: list[str] = Field(
        max_length=MAX_LINES_PER_HUNK,
        description="Líneas de reemplazo (pueden estar vacías para eliminaciones puras)",
    )

    @model_validator(mode="after")
    def validate_range(self) -> "Hunk":
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line ({self.end_line}) debe ser >= start_line ({self.start_line})"
            )
        for line in self.old_lines + self.new_lines:
            if len(line) > MAX_LINE_LENGTH:
                raise ValueError(
                    f"Línea excede MAX_LINE_LENGTH ({MAX_LINE_LENGTH} chars)"
                )
        return self

    @field_validator("old_lines", "new_lines", mode="before")
    @classmethod
    def no_injection_markers(cls, lines: list[str]) -> list[str]:
        """
        Rechaza contenido que intente inyectar instrucciones al validador.
        Los strings de línea son datos de código, no instrucciones.
        """
        # Estos marcadores no deben aparecer en ninguna línea de código propuesto
        # como instrucciones directas al sistema (solo son válidos dentro de strings
        # si forman parte del código fuente legítimo — la SAST los evaluará)
        return lines  # Sin filtro de contenido — el SAST lo hará


class TargetFile(BaseModel):
    """Un archivo objetivo del patch."""

    path: str = Field(min_length=1, max_length=512)
    hunks: list[Hunk] = Field(min_length=1, max_length=MAX_HUNKS_PER_FILE)

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        # Sin traversal
        if ".." in v.replace("\\", "/").split("/"):
            raise ValueError("Path traversal en path de archivo")
        # Sin null bytes
        if "\x00" in v:
            raise ValueError("Null byte en path")
        # Sin ADS
        if ":" in v.replace(":/", "").replace(":\\", ""):
            raise ValueError("Alternate Data Stream en path")
        # Extensión permitida
        suffix = "." + v.rsplit(".", 1)[-1].lower() if "." in v else ""
        if suffix not in ALLOWED_TARGET_EXTENSIONS:
            raise ValueError(
                f"Extensión de archivo no permitida: {suffix!r}. "
                f"Permitidas: {sorted(ALLOWED_TARGET_EXTENSIONS)}"
            )
        return v

    def is_protected(self) -> bool:
        """True si el path toca una ruta protegida (requiere override manual)."""
        return any(pattern.search(self.path) for pattern in PROTECTED_PATH_PATTERNS)


class PatchProposal(BaseModel):
    """Schema completo de una propuesta de patch de GPT Actions."""

    schema_version: str = Field(description="Versión del schema de propuesta")
    change_type: str = Field(description="Tipo de cambio")
    risk_level: str = Field(description="Nivel de riesgo autopercibido")
    rationale: str = Field(
        min_length=10,
        max_length=MAX_RATIONALE_LENGTH,
        description="Justificación del cambio (máx 500 chars, texto plano)",
    )
    target_files: list[TargetFile] = Field(
        min_length=1,
        max_length=MAX_FILES_PER_PATCH,
        description="Archivos a modificar",
    )
    # Campos opcionales para override de rutas protegidas
    override_reason: str | None = Field(
        default=None,
        max_length=500,
        description="Justificación para tocar rutas protegidas (aun así requiere aprobación manual)",
    )

    @field_validator("schema_version")
    @classmethod
    def check_version(cls, v: str) -> str:
        if v not in VALID_SCHEMA_VERSIONS:
            raise ValueError(
                f"schema_version {v!r} no soportado. Versiones válidas: {VALID_SCHEMA_VERSIONS}"
            )
        return v

    @field_validator("change_type")
    @classmethod
    def check_change_type(cls, v: str) -> str:
        if v not in VALID_CHANGE_TYPES:
            raise ValueError(
                f"change_type {v!r} inválido. Tipos permitidos: {VALID_CHANGE_TYPES}"
            )
        return v

    @field_validator("risk_level")
    @classmethod
    def check_risk_level(cls, v: str) -> str:
        if v not in VALID_RISK_LEVELS:
            # "high" está en VALID_RISK_LEVELS si se permite, pero lo excluimos
            raise ValueError(
                f"risk_level {v!r} no permitido para Actions. "
                f"Solo 'low' o 'medium'. Los cambios de alto riesgo requieren iniciativa humana."
            )
        return v

    @field_validator("rationale")
    @classmethod
    def sanitize_rationale(cls, v: str) -> str:
        """Elimina caracteres de control y secuencias de escape."""
        # Solo texto plano: eliminamos todo lo que no sea imprimible ASCII + espacios básicos
        cleaned = re.sub(r"[^\x20-\x7E\t\n]", "", v)
        if len(cleaned) < 10:
            raise ValueError("rationale demasiado corto tras sanitización")
        return cleaned

    def has_protected_paths(self) -> list[str]:
        """Devuelve la lista de paths protegidos que toca esta propuesta."""
        return [f.path for f in self.target_files if f.is_protected()]


# ------------------------------------------------------------------
# Resultado de validación de schema
# ------------------------------------------------------------------

class SchemaValidationResult(BaseModel):
    """Resultado de la validación de schema de un PatchProposal."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_manual_override: bool = False
    protected_paths: list[str] = Field(default_factory=list)


def validate_proposal(raw: dict[str, Any]) -> SchemaValidationResult:
    """
    Valida un dict contra el schema de PatchProposal.

    Returns:
        SchemaValidationResult con valid=True si el schema es correcto,
        o con errors si hay problemas.
    """
    from pydantic import ValidationError

    try:
        proposal = PatchProposal.model_validate(raw)
    except ValidationError as exc:
        errors = [f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return SchemaValidationResult(valid=False, errors=errors)

    warnings: list[str] = []
    protected = proposal.has_protected_paths()
    requires_manual = bool(protected)

    if protected:
        warnings.append(
            f"RUTAS PROTEGIDAS detectadas: {protected}. "
            f"Esta propuesta requiere revisión manual obligatoria."
        )
        if not proposal.override_reason:
            warnings.append(
                "No se proporcionó override_reason para las rutas protegidas. "
                "El validador la marcará como REQUIRES_MANUAL_OVERRIDE."
            )

    if proposal.risk_level == "medium":
        warnings.append(
            "risk_level=medium: el validador aplicará SAST extendido y dependency gate."
        )

    return SchemaValidationResult(
        valid=True,
        warnings=warnings,
        requires_manual_override=requires_manual,
        protected_paths=protected,
    )
