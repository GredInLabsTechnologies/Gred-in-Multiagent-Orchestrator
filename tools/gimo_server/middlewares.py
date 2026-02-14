import asyncio
import hashlib
import logging
import time
import traceback
import uuid
from typing import Callable, Coroutine

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from tools.gimo_server.config import CORS_ORIGINS, TOKENS
from tools.gimo_server.security.threat_level import ThreatLevel

logger = logging.getLogger("orchestrator")


async def threat_level_middleware(
    request: Request, call_next: Callable[[Request], Coroutine[None, None, Response]]
) -> Response:
    """Adaptive security middleware based on threat levels."""
    # Always allow root, health, and resolve endpoints
    if request.url.path in ["/", "/health", "/ui/security/resolve"]:
        return await call_next(request)

    from tools.gimo_server.security import threat_engine

    current_level = threat_engine.level

    # 1. NOMINAL / ALERT: Normal operation
    if current_level < ThreatLevel.GUARDED:
        response = await call_next(request)
        response.headers["X-Threat-Level"] = threat_engine.level_label
        return response

    # 2. Check if request is authenticated - auth users are NEVER blocked
    auth_header = request.headers.get("Authorization", "")
    is_authenticated = False
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token in TOKENS:
            is_authenticated = True

    if is_authenticated:
        response = await call_next(request)
        response.headers["X-Threat-Level"] = threat_engine.level_label
        return response

    # 3. GUARDED: Unauthenticated requests are throttled
    if current_level == ThreatLevel.GUARDED:
        # Artificial delay for unauthenticated traffic
        await asyncio.sleep(1.0)
        response = await call_next(request)
        response.headers["X-Threat-Level"] = threat_engine.level_label
        return response

    # 4. LOCKDOWN: Unauthenticated requests are blocked
    if current_level >= ThreatLevel.LOCKDOWN:
        return Response(
            status_code=503,
            content=f"System in PROTECTIVE LOCKDOWN ({threat_engine.level_label}). Authenticate to proceed.",
            headers={"X-Threat-Level": threat_engine.level_label}
        )

    return await call_next(request)


async def allow_options_preflight_middleware(
    request: Request, call_next: Callable[[Request], Coroutine[None, None, Response]]
) -> Response:
    """Handle CORS preflight requests."""
    origin = request.headers.get("origin")
    allowed_origin = origin if origin in CORS_ORIGINS else None

    if request.method == "OPTIONS":
        req_headers = request.headers.get("access-control-request-headers", "*")
        headers = {
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": req_headers,
            "Access-Control-Allow-Credentials": "true",
        }
        if allowed_origin:
            headers["Access-Control-Allow-Origin"] = allowed_origin
        return Response(status_code=204, headers=headers)

    response = await call_next(request)
    if allowed_origin:
        response.headers.setdefault("Access-Control-Allow-Origin", allowed_origin)
        response.headers.setdefault("Access-Control-Allow-Credentials", "true")
    return response


async def correlation_id_middleware(
    request: Request, call_next: Callable[[Request], Coroutine[None, None, Response]]
) -> Response:
    """Add correlation ID to request and response, and log the request."""
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id

    start_time = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Correlation-ID"] = correlation_id

    logger.info(
        "Request handled",
        extra={
            "correlation_id": correlation_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return response


async def _capture_payload_hash(request: Request) -> str:
    """Helper to capture and hash request payload."""
    try:
        body_bytes = await request.body()
        if not body_bytes:
            return "empty"
        return hashlib.sha256(body_bytes).hexdigest()
    except Exception:
        return "read_error"


async def adaptive_panic_catcher_middleware(
    request: Request, call_next: Callable[[Request], Coroutine[None, None, Response]]
) -> Response:
    """Global exception handler that reports to ThreatEngine."""
    try:
        return await call_next(request)
    except Exception as e:
        # Ignore known HTTP exceptions (logic flow controls)
        if isinstance(e, (StarletteHTTPException, RequestValidationError)):
            raise e

        # 1. Generate Correlation ID
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))

        # 2. Capture & Hash Payload (Never log raw payload)
        payload_hash = await _capture_payload_hash(request)

        # 3. Extract Actor (Best Effort)
        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        actor_snippet = "authenticated" if token else "anonymous"
        client_ip = request.client.host if request.client else "unknown"

        from tools.gimo_server.security import audit, threat_engine

        # 4. Log Critical Panic via Audit
        audit.log_panic(
            correlation_id=correlation_id,
            reason=str(e),
            payload_hash=payload_hash,
            actor=actor_snippet,
            traceback_str=traceback.format_exc(),
        )

        # 5. Report to ThreatEngine (ADAPTIVE ESCALATION)
        # Operational exceptions like ConnectionError will NOT escalate target level.
        threat_engine.record_exception(
            source=client_ip,
            exc=e,
            detail=f"Correlation ID: {correlation_id}"
        )

        # 6. Return Opaque Error
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal System Failure",
                "correlation_id": correlation_id,
                "threat_level": threat_engine.level_label,
                "message": "System has entered protective defense mode.",
            },
        )


def register_middlewares(app):
    """
    Register all middlewares in the correct order.
    The order here is significant because Starlette middlewares are processed as a stack.
    Requests pass through them in reverse order of registration.
    """
    app.middleware("http")(threat_level_middleware)
    app.middleware("http")(allow_options_preflight_middleware)
    app.middleware("http")(correlation_id_middleware)
    app.middleware("http")(adaptive_panic_catcher_middleware)
