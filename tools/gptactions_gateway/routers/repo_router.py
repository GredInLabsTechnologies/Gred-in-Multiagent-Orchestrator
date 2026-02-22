"""
Router de acceso de solo-lectura al repositorio para GPT Actions.

Solo expone:
  GET /repo/manifest  → Lista de archivos que Actions tiene permitido leer
  GET /repo/file      → Contenido de un archivo del manifest

Principio: Actions no puede descubrir rutas por su cuenta.
Solo puede leer los archivos explícitamente listados en el manifest.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger("gptactions.repo_router")

router = APIRouter(prefix="/repo", tags=["repo"])

# Extensiones que Actions puede leer del manifest
READABLE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".rs", ".c", ".cpp", ".h",
    ".json", ".yaml", ".yml", ".toml", ".cfg",
}

# Límites de lectura
MAX_READ_BYTES = 65_536   # 64 KB por archivo
MAX_READ_LINES = 500


# ------------------------------------------------------------------
# Modelos
# ------------------------------------------------------------------

class ManifestEntry(BaseModel):
    path: str
    size_bytes: int
    extension: str


class ManifestResponse(BaseModel):
    total_files: int
    files: list[ManifestEntry]
    generated_at: str


class FileResponse(BaseModel):
    path: str
    content: str
    total_lines: int
    truncated: bool
    content_hash: str


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def get_jail(request: Request):
    return request.app.state.jail


def get_audit(request: Request):
    return request.app.state.audit


def _load_manifest(jail) -> list[dict[str, Any]]:
    """Carga el manifest de archivos legibles desde el jail."""
    manifest_path = jail.root / "manifest" / "readable_files.json"
    if not manifest_path.exists():
        return []
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data.get("files", [])
    except Exception as exc:
        logger.warning("Error al cargar manifest: %s", exc)
        return []


def _path_in_manifest(path: str, manifest: list[dict]) -> bool:
    return any(entry.get("path") == path for entry in manifest)


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get(
    "/manifest",
    response_model=ManifestResponse,
    summary="Lista de archivos que Actions puede leer",
    description=(
        "Devuelve únicamente los archivos explícitamente listados "
        "en el manifest de lectura del jail. Actions no puede "
        "explorar el filesystem más allá de esta lista."
    ),
)
async def get_manifest(request: Request, jail=Depends(get_jail)) -> ManifestResponse:
    import time

    audit = get_audit(request)
    src_ip = request.client.host if request.client else "unknown"

    manifest_entries = _load_manifest(jail)

    audit.append(
        event="MANIFEST_READ",
        src_ip=src_ip,
        payload_hash="N/A",
        actor_hash=_actor_hash(request),
        outcome="ALLOWED",
        detail=f"files_in_manifest={len(manifest_entries)}",
    )

    files = []
    for entry in manifest_entries:
        path = entry.get("path", "")
        ext = Path(path).suffix.lower()
        if ext not in READABLE_EXTENSIONS:
            continue
        files.append(
            ManifestEntry(
                path=path,
                size_bytes=entry.get("size_bytes", 0),
                extension=ext,
            )
        )

    return ManifestResponse(
        total_files=len(files),
        files=files,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


@router.get(
    "/file",
    response_model=FileResponse,
    summary="Leer el contenido de un archivo del manifest",
    description=(
        "Lee el contenido de un archivo listado en el manifest. "
        "Si el archivo no está en el manifest, se devuelve 403. "
        "El contenido se trunca a 500 líneas / 64 KB."
    ),
)
async def read_file(
    request: Request,
    path: str = Query(..., min_length=1, max_length=512, description="Ruta relativa al repo"),
    start_line: int = Query(1, ge=1, description="Línea inicial (1-based)"),
    jail=Depends(get_jail),
) -> FileResponse:
    audit = get_audit(request)
    src_ip = request.client.host if request.client else "unknown"

    # 1. Verificar que la ruta está en el manifest (no en el jail general)
    manifest_entries = _load_manifest(jail)
    if not _path_in_manifest(path, manifest_entries):
        audit.append(
            event="FILE_READ_FORBIDDEN",
            src_ip=src_ip,
            payload_hash=hashlib.sha256(path.encode()).hexdigest(),
            actor_hash=_actor_hash(request),
            outcome="DENIED",
            detail=f"path={path!r} no está en el manifest",
        )
        raise HTTPException(
            status_code=403,
            detail=f"Archivo no disponible: {path!r} no está en el manifest de lectura",
        )

    # 2. Extensión permitida
    ext = Path(path).suffix.lower()
    if ext not in READABLE_EXTENSIONS:
        raise HTTPException(
            status_code=403,
            detail=f"Extensión {ext!r} no permitida para lectura",
        )

    # 3. Leer desde el repo raíz (NO desde el jail de patches)
    #    El manifest debe contener rutas relativas al repo raíz
    try:
        from tools.gptactions_gateway.security.jail import JailViolation
        # Para lectura, usamos el repo root, no el jail de patches
        # La ruta viene del manifest (ya validada), pero aun así pasamos por jail.resolve
        # para protección adicional
        repo_root = jail.root.parent.parent  # Subimos desde el jail hasta el repo
        target = (repo_root / path).resolve()

        # Verificar que no sale del repo root
        try:
            target.relative_to(repo_root)
        except ValueError:
            raise JailViolation(f"Ruta {path!r} escapa del repo root")

        if not target.exists() or not target.is_file():
            raise FileNotFoundError(path)

        raw_bytes = target.read_bytes()
        if len(raw_bytes) > MAX_READ_BYTES:
            raw_bytes = raw_bytes[:MAX_READ_BYTES]
            truncated = True
        else:
            truncated = False

        content = raw_bytes.decode("utf-8", errors="replace")
        lines = content.splitlines()
        if len(lines) > MAX_READ_LINES:
            lines = lines[start_line - 1 : start_line - 1 + MAX_READ_LINES]
            truncated = True
        else:
            lines = lines[start_line - 1 :]

        final_content = "\n".join(lines)
        content_hash = hashlib.sha256(final_content.encode()).hexdigest()

    except FileNotFoundError:
        audit.append(
            event="FILE_NOT_FOUND",
            src_ip=src_ip,
            payload_hash=hashlib.sha256(path.encode()).hexdigest(),
            actor_hash=_actor_hash(request),
            outcome="ERROR",
            detail=f"path={path!r} no encontrado en disco",
        )
        raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {path!r}")
    except Exception as exc:
        audit.append(
            event="FILE_READ_ERROR",
            src_ip=src_ip,
            payload_hash=hashlib.sha256(path.encode()).hexdigest(),
            actor_hash=_actor_hash(request),
            outcome="ERROR",
            detail=str(exc)[:200],
        )
        raise HTTPException(status_code=500, detail="Error interno al leer el archivo")

    audit.append(
        event="FILE_READ",
        src_ip=src_ip,
        payload_hash=content_hash,
        actor_hash=_actor_hash(request),
        outcome="ALLOWED",
        detail=f"path={path!r} lines={len(lines)} truncated={truncated}",
    )

    return FileResponse(
        path=path,
        content=final_content,
        total_lines=len(lines),
        truncated=truncated,
        content_hash=content_hash,
    )


def _actor_hash(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return hashlib.sha256(auth[7:].encode()).hexdigest()[:16] + "…"
    return "no-token"
