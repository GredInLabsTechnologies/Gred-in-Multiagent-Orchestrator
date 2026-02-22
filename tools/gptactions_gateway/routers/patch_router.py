"""
Router de propuestas de patch para el gateway de GPT Actions.

Fase A del pipeline: Actions propone, NUNCA ejecuta.

Endpoints:
    POST /patch/propose  → Crea una propuesta de patch en el jail
    GET  /patch/status/{patch_id} → Estado de un patch
    GET  /patch/list     → Lista patches pendientes (para monitoreo)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from tools.gptactions_gateway import config as cfg
from tools.gptactions_gateway.security.jail import Jail, JailViolation, PatchQuotaExceeded
from tools.gptactions_gateway.security.patch_schema import validate_proposal

logger = logging.getLogger("gptactions.patch_router")

router = APIRouter(prefix="/patch", tags=["patch"])


# ------------------------------------------------------------------
# Modelos de respuesta
# ------------------------------------------------------------------

class ProposeResponse(BaseModel):
    patch_id: str
    status: str
    message: str
    requires_manual_override: bool
    warnings: list[str]
    created_at: str


class PatchStatusResponse(BaseModel):
    patch_id: str
    status: str       # pending | validated | rejected | archived
    created_at: str
    size_bytes: int
    requires_manual_override: bool


class PatchListResponse(BaseModel):
    count: int
    patches: list[str]
    max_allowed: int


# ------------------------------------------------------------------
# Estado interno de patches (in-memory, complementa al filesystem)
# ------------------------------------------------------------------

_patch_meta: dict[str, dict[str, Any]] = {}


# ------------------------------------------------------------------
# Dependency: extraer contexto de request
# ------------------------------------------------------------------

def get_jail(request: Request) -> Jail:
    return request.app.state.jail


def get_audit(request: Request):
    return request.app.state.audit


# ------------------------------------------------------------------
# Rate limiting de patches (simple in-memory por IP)
# ------------------------------------------------------------------

_patch_rate: dict[str, list[float]] = {}


def _check_patch_rate(src_ip: str) -> None:
    """Comprueba que la IP no supere PATCH_RATE_LIMIT_PER_HOUR propuestas/hora."""
    now = time.time()
    window = 3600  # 1 hora
    timestamps = _patch_rate.get(src_ip, [])
    # Limpiar timestamps viejos
    timestamps = [t for t in timestamps if now - t < window]
    if len(timestamps) >= cfg.PATCH_RATE_LIMIT_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit de patches alcanzado: máximo {cfg.PATCH_RATE_LIMIT_PER_HOUR} "
                f"propuestas por hora por IP"
            ),
        )
    timestamps.append(now)
    _patch_rate[src_ip] = timestamps


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post(
    "/propose",
    response_model=ProposeResponse,
    summary="Proponer un cambio de código (no ejecuta nada)",
    description=(
        "**x-openai-isConsequential: true** — Siempre requiere confirmación.\n\n"
        "Crea una propuesta de patch en el jail de filesystem. "
        "La propuesta NUNCA se aplica automáticamente: requiere pasar la "
        "cadena de validación (Fase B) y aprobación humana (Fase C)."
    ),
)
async def propose_patch(
    request: Request,
    jail: Jail = Depends(get_jail),
) -> ProposeResponse:
    src_ip = request.client.host if request.client else "unknown"
    audit = request.app.state.audit

    # Rate limit específico de patches
    try:
        _check_patch_rate(src_ip)
    except HTTPException:
        body_hash = "N/A"
        audit.append(
            event="PATCH_RATE_LIMITED",
            src_ip=src_ip,
            payload_hash=body_hash,
            actor_hash=_actor_hash(request),
            outcome="DENIED",
            detail="Rate limit de patches/hora alcanzado",
        )
        raise

    # Leer y hashear el body
    body_bytes = await request.body()
    payload_hash = hashlib.sha256(body_bytes).hexdigest()

    try:
        raw = json.loads(body_bytes)
    except json.JSONDecodeError:
        audit.append(
            event="PATCH_INVALID_JSON",
            src_ip=src_ip,
            payload_hash=payload_hash,
            actor_hash=_actor_hash(request),
            outcome="DENIED",
            detail="Body no es JSON válido",
        )
        raise HTTPException(status_code=400, detail="Body debe ser JSON válido")

    # Validación estricta de schema
    result = validate_proposal(raw)
    if not result.valid:
        audit.append(
            event="PATCH_SCHEMA_INVALID",
            src_ip=src_ip,
            payload_hash=payload_hash,
            actor_hash=_actor_hash(request),
            outcome="DENIED",
            detail=f"Errores de schema: {result.errors}",
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": "La propuesta no cumple el schema requerido",
                "errors": result.errors,
            },
        )

    # Generar ID único y metadatos
    patch_id = str(uuid.uuid4())
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Enriquecer el payload con metadatos de auditoría antes de guardarlo
    enriched = {
        **raw,
        "_meta": {
            "patch_id": patch_id,
            "created_at": created_at,
            "src_ip": src_ip,
            "payload_hash": payload_hash,
            "requires_manual_override": result.requires_manual_override,
            "schema_warnings": result.warnings,
            "protected_paths": result.protected_paths,
            "status": "pending",
        },
    }
    enriched_bytes = json.dumps(enriched, ensure_ascii=True, indent=2).encode("utf-8")

    # Escribir en el jail
    try:
        jail.write_patch(f"{patch_id}.json", enriched_bytes)
    except PatchQuotaExceeded as exc:
        audit.append(
            event="PATCH_QUOTA_EXCEEDED",
            src_ip=src_ip,
            payload_hash=payload_hash,
            actor_hash=_actor_hash(request),
            outcome="DENIED",
            detail=str(exc),
        )
        raise HTTPException(status_code=429, detail=str(exc))
    except JailViolation as exc:
        audit.append(
            event="PATCH_JAIL_VIOLATION",
            src_ip=src_ip,
            payload_hash=payload_hash,
            actor_hash=_actor_hash(request),
            outcome="DENIED",
            detail=str(exc),
        )
        raise HTTPException(status_code=403, detail=f"Violación de seguridad: {exc}")

    # Registrar en memoria y en audit log
    _patch_meta[patch_id] = {
        "created_at": created_at,
        "src_ip": src_ip,
        "payload_hash": payload_hash,
        "requires_manual_override": result.requires_manual_override,
        "status": "pending",
    }

    audit.append(
        event="PATCH_PROPOSED",
        src_ip=src_ip,
        payload_hash=payload_hash,
        actor_hash=_actor_hash(request),
        outcome="PENDING",
        detail=(
            f"patch_id={patch_id} "
            f"files={len(raw.get('target_files', []))} "
            f"requires_manual={result.requires_manual_override}"
        ),
    )

    logger.info(
        "Patch propuesto: id=%s ip=%s files=%d manual=%s",
        patch_id,
        src_ip,
        len(raw.get("target_files", [])),
        result.requires_manual_override,
    )

    return ProposeResponse(
        patch_id=patch_id,
        status="pending",
        message=(
            "Propuesta recibida. Pasará por validación automática (SAST + secret scan + "
            "dependency gate) antes de ser elegible para aprobación humana."
        ),
        requires_manual_override=result.requires_manual_override,
        warnings=result.warnings,
        created_at=created_at,
    )


@router.get(
    "/status/{patch_id}",
    response_model=PatchStatusResponse,
    summary="Estado de una propuesta de patch",
)
async def get_patch_status(
    patch_id: str,
    request: Request,
    jail: Jail = Depends(get_jail),
) -> PatchStatusResponse:
    src_ip = request.client.host if request.client else "unknown"

    # Validar formato del patch_id (UUID hex)
    import re
    if not re.fullmatch(r"[a-f0-9\-]{32,36}", patch_id.lower()):
        raise HTTPException(status_code=400, detail="patch_id inválido")

    # Comprobar si existe en el jail
    try:
        raw_bytes = jail.read_patch(patch_id)
        data = json.loads(raw_bytes)
        meta = data.get("_meta", {})
        return PatchStatusResponse(
            patch_id=patch_id,
            status=meta.get("status", "pending"),
            created_at=meta.get("created_at", ""),
            size_bytes=len(raw_bytes),
            requires_manual_override=meta.get("requires_manual_override", False),
        )
    except FileNotFoundError:
        # Puede estar archivado
        if patch_id in _patch_meta:
            m = _patch_meta[patch_id]
            return PatchStatusResponse(
                patch_id=patch_id,
                status=m.get("status", "archived"),
                created_at=m.get("created_at", ""),
                size_bytes=0,
                requires_manual_override=m.get("requires_manual_override", False),
            )
        raise HTTPException(status_code=404, detail="Patch no encontrado")


@router.get(
    "/list",
    response_model=PatchListResponse,
    summary="Lista patches pendientes (solo para monitoreo)",
)
async def list_patches(
    request: Request,
    jail: Jail = Depends(get_jail),
) -> PatchListResponse:
    from tools.gptactions_gateway.security.jail import MAX_PENDING_PATCHES
    pending = jail.list_patches()
    return PatchListResponse(
        count=len(pending),
        patches=pending,
        max_allowed=MAX_PENDING_PATCHES,
    )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _actor_hash(request: Request) -> str:
    """SHA-256 truncado del token Bearer (no loggeamos el token en claro)."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        return hashlib.sha256(token.encode()).hexdigest()[:16] + "…"
    return "no-token"
