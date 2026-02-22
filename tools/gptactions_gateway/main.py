"""
Gateway FastAPI para GPT Actions.

Este proceso es el único punto de contacto entre ChatGPT Actions y el sistema.
Corre en un puerto separado (9326) con su propio token de autenticación.

Capas de defensa en orden de ejecución por request:
  1. TLS (manejado por el reverse proxy — nginx/caddy en producción)
  2. IP allowlist middleware (OpenAI egress IPs)
  3. Auth middleware (Bearer token)
  4. Rate limiting middleware (global + por endpoint)
  5. Request logging al audit chain
  6. Schema validation (en los routers)
  7. Jail enforcement (en los routers)

Actions NUNCA puede:
  - Ejecutar código o comandos
  - Leer archivos fuera del manifest
  - Escribir fuera del jail
  - Acceder a otros servicios o puertos
  - Alcanzar el proceso validador (Fase B)
"""
from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tools.gptactions_gateway import config as cfg
from tools.gptactions_gateway.routers.patch_router import router as patch_router
from tools.gptactions_gateway.routers.repo_router import router as repo_router
from tools.gptactions_gateway.security.chain_audit import ChainedAuditLog
from tools.gptactions_gateway.security.ip_allowlist import IPAllowlist
from tools.gptactions_gateway.security.jail import Jail

logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gptactions.main")


# ------------------------------------------------------------------
# Lifespan: inicialización y limpieza
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Inicialización
    cfg.GATEWAY_DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)

    app.state.jail = Jail(cfg.JAIL_ROOT)
    app.state.audit = ChainedAuditLog(cfg.LOG_DIR / "gptactions_audit.jsonl")
    app.state.ip_allowlist = IPAllowlist(
        cfg.IP_ALLOWLIST_PATH,
        bypass_loopback=cfg.BYPASS_LOOPBACK,
        bypass_private=cfg.BYPASS_PRIVATE,
    )

    logger.info(
        "Gateway GPT Actions iniciado | jail=%s | IPs=%d CIDRs | puerto=%d",
        cfg.JAIL_ROOT,
        app.state.ip_allowlist.cidr_count,
        cfg.PORT,
    )

    # Iniciar tarea de limpieza de patches TTL expirados
    import asyncio
    cleanup_task = asyncio.create_task(_ttl_cleanup_loop(app))

    yield

    # Cleanup
    cleanup_task.cancel()
    logger.info("Gateway GPT Actions detenido")


# ------------------------------------------------------------------
# App
# ------------------------------------------------------------------

app = FastAPI(
    title="GPT Actions Gateway",
    description=(
        "Gateway de solo-propuesta para ChatGPT Actions. "
        "Actions solo puede leer el manifest y proponer patches. "
        "Nada se ejecuta sin validación independiente y aprobación humana."
    ),
    version="1.0.0",
    docs_url="/docs" if cfg.DEBUG else None,     # Swagger deshabilitado en producción
    redoc_url="/redoc" if cfg.DEBUG else None,
    openapi_url="/openapi.json" if cfg.DEBUG else None,
    lifespan=lifespan,
)

# CORS: en producción, sin wildcards — solo el dominio del GPT
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chat.openai.com"] if not cfg.DEBUG else ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ------------------------------------------------------------------
# Middleware: IP Allowlist (primera línea de defensa)
# ------------------------------------------------------------------

@app.middleware("http")
async def ip_allowlist_middleware(request: Request, call_next):
    src_ip = request.client.host if request.client else "0.0.0.0"

    # Health check no requiere IP allowlist (para monitoreo interno)
    if request.url.path == "/health":
        return await call_next(request)

    ip_allowlist: IPAllowlist = request.app.state.ip_allowlist

    # Advertir si el allowlist está obsoleto
    if ip_allowlist.is_stale and cfg.BLOCK_ON_STALE_ALLOWLIST:
        logger.error("Allowlist de IPs OBSOLETO — bloqueando todos los requests externos")
        audit: ChainedAuditLog = request.app.state.audit
        audit.append(
            event="STALE_ALLOWLIST_BLOCK",
            src_ip=src_ip,
            payload_hash="N/A",
            actor_hash="N/A",
            outcome="DENIED",
            detail="allowlist de IPs obsoleto — ejecuta sync_openai_ips.py",
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Servicio no disponible: configuración de red desactualizada"},
        )

    allowed, reason = ip_allowlist.is_allowed(src_ip)
    if not allowed:
        audit: ChainedAuditLog = request.app.state.audit
        audit.append(
            event="IP_BLOCKED",
            src_ip=src_ip,
            payload_hash="N/A",
            actor_hash="N/A",
            outcome="DENIED",
            detail=f"IP no en allowlist: {reason}",
        )
        logger.warning("IP bloqueada: %s (%s)", src_ip, reason)
        return JSONResponse(
            status_code=403,
            content={"detail": "Acceso denegado"},
        )

    return await call_next(request)


# ------------------------------------------------------------------
# Middleware: Autenticación Bearer
# ------------------------------------------------------------------

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Health check es público
    if request.url.path == "/health":
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""

    if not token or token != cfg.GATEWAY_TOKEN:
        src_ip = request.client.host if request.client else "unknown"
        audit: ChainedAuditLog = request.app.state.audit
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:16] if token else "empty"
        audit.append(
            event="AUTH_FAILURE",
            src_ip=src_ip,
            payload_hash="N/A",
            actor_hash=token_hash + "…",
            outcome="DENIED",
            detail="Token Bearer inválido o ausente",
        )
        return JSONResponse(
            status_code=401,
            content={"detail": "Token de autenticación inválido"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


# ------------------------------------------------------------------
# Middleware: Rate limiting global
# ------------------------------------------------------------------

_rate_buckets: dict[str, list[float]] = defaultdict(list)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    src_ip = request.client.host if request.client else "0.0.0.0"
    now = time.time()
    window = 60.0  # 1 minuto

    bucket = _rate_buckets[src_ip]
    bucket[:] = [t for t in bucket if now - t < window]

    if len(bucket) >= cfg.RATE_LIMIT_PER_MIN:
        audit: ChainedAuditLog = request.app.state.audit
        audit.append(
            event="RATE_LIMITED",
            src_ip=src_ip,
            payload_hash="N/A",
            actor_hash="N/A",
            outcome="DENIED",
            detail=f"Rate limit global: {cfg.RATE_LIMIT_PER_MIN} req/min",
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Demasiadas solicitudes. Inténtelo de nuevo en un minuto."},
            headers={"Retry-After": "60"},
        )

    bucket.append(now)
    return await call_next(request)


# ------------------------------------------------------------------
# Middleware: Request logging al audit chain
# ------------------------------------------------------------------

@app.middleware("http")
async def request_audit_middleware(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    src_ip = request.client.host if request.client else "unknown"
    start = time.time()

    # No consumimos el body aquí (lo hacen los routers que lo necesitan)
    response = await call_next(request)

    duration_ms = int((time.time() - start) * 1000)
    audit: ChainedAuditLog = request.app.state.audit
    auth = request.headers.get("authorization", "")
    actor = (
        hashlib.sha256(auth[7:].encode()).hexdigest()[:16] + "…"
        if auth.startswith("Bearer ")
        else "no-token"
    )
    audit.append(
        event="HTTP_REQUEST",
        src_ip=src_ip,
        payload_hash="N/A",
        actor_hash=actor,
        outcome=str(response.status_code),
        detail=f"method={request.method} path={request.url.path} ms={duration_ms}",
    )

    return response


# ------------------------------------------------------------------
# Routers
# ------------------------------------------------------------------

app.include_router(repo_router)
app.include_router(patch_router)


# ------------------------------------------------------------------
# Endpoints básicos
# ------------------------------------------------------------------

@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok", "service": "gptactions-gateway"}


@app.get(
    "/status",
    summary="Estado del gateway",
    description="Información básica del gateway. No incluye datos sensibles.",
)
async def gateway_status(request: Request):
    ip_allowlist: IPAllowlist = request.app.state.ip_allowlist
    jail: Jail = request.app.state.jail
    audit: ChainedAuditLog = request.app.state.audit

    chain_ok, chain_msg = audit.verify_chain()

    return {
        "service": "gptactions-gateway",
        "version": "1.0.0",
        "ip_allowlist": {
            "cidrs_loaded": ip_allowlist.cidr_count,
            "is_stale": ip_allowlist.is_stale,
        },
        "jail": {
            "root": str(jail.root),
            "pending_patches": jail.count_pending_patches(),
        },
        "audit_chain": {
            "intact": chain_ok,
            "message": chain_msg,
        },
    }


# ------------------------------------------------------------------
# TTL cleanup de patches
# ------------------------------------------------------------------

async def _ttl_cleanup_loop(application: FastAPI) -> None:
    """Archiva patches pendientes más antiguos que PATCH_TTL_SECONDS."""
    import asyncio
    import json

    while True:
        await asyncio.sleep(3600)  # Revisar cada hora
        try:
            jail: Jail = application.state.jail
            audit: ChainedAuditLog = application.state.audit
            now = time.time()
            for patch_id in jail.list_patches():
                try:
                    raw = jail.read_patch(patch_id)
                    data = json.loads(raw)
                    meta = data.get("_meta", {})
                    created_at_str = meta.get("created_at", "")
                    # Parsear timestamp
                    from datetime import datetime, timezone
                    created_dt = datetime.fromisoformat(
                        created_at_str.replace("Z", "+00:00")
                    )
                    age = now - created_dt.timestamp()
                    if age > cfg.PATCH_TTL_SECONDS:
                        jail.archive_patch(patch_id, reason="ttl-expired")
                        audit.append(
                            event="PATCH_TTL_EXPIRED",
                            src_ip="system",
                            payload_hash=patch_id,
                            actor_hash="ttl-cleaner",
                            outcome="ARCHIVED",
                            detail=f"patch_id={patch_id} age={int(age)}s",
                        )
                        logger.info("Patch archivado por TTL: %s (age=%ds)", patch_id, int(age))
                except Exception as exc:
                    logger.warning("Error en TTL cleanup para %s: %s", patch_id, exc)
        except Exception as exc:
            logger.error("Error en TTL cleanup loop: %s", exc)


# ------------------------------------------------------------------
# Punto de entrada directo
# ------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "tools.gptactions_gateway.main:app",
        host=cfg.HOST,
        port=cfg.PORT,
        log_level=cfg.LOG_LEVEL.lower(),
        reload=cfg.DEBUG,
    )
