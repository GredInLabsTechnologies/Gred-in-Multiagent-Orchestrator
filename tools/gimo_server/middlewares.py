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
from tools.gimo_server.security import load_security_db, save_security_db
from tools.gimo_server.security.audit import log_panic

logger = logging.getLogger("orchestrator")


async def panic_mode_check_middleware(
    request: Request, call_next: Callable[[Request], Coroutine[None, None, Response]]
) -> Response:
    """Block unauthenticated requests during panic mode. Authenticated users can still operate."""
    # Always allow root and resolve endpoints
    if request.url.path in ["/", "/health", "/ui/security/resolve"]:
        return await call_next(request)

    # Use the loader from the security module so tests can patch it
    from tools.gimo_server import security as security_module

    db = security_module.load_security_db()
    if db.get("panic_mode", False):
        # Check if request has valid token - if so, allow through
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if token in TOKENS:
                # Valid token - allow authenticated users during lockdown
                return await call_next(request)

        # No valid token during lockdown - block external attackers
        return Response(
            status_code=503,
            content="System in LOCKDOWN. Use /ui/security/resolve to clear panic mode.",
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


EXCEPTION_PANIC_THRESHOLD = 3  # Exceptions before lockdown
EXCEPTION_WINDOW_SECONDS = 60  # Time window for threshold


def _record_panic_event(correlation_id: str, e: Exception) -> None:
    """Record exception event and activate panic mode only if threshold exceeded."""
    now = time.time()

    try:
        db = load_security_db()
        recent_events = db.get("recent_events", [])

        # Count recent unhandled exceptions within time window
        recent_exceptions = [
            ev
            for ev in recent_events
            if ev.get("type") == "PANIC"
            and isinstance(ev.get("timestamp"), (int, float))
            and (now - ev["timestamp"]) < EXCEPTION_WINDOW_SECONDS
            and not ev.get("resolved", False)
        ]

        # Add new event (timestamp as float for consistency)
        recent_events.append(
            {
                "type": "PANIC",
                "timestamp": now,
                "correlation_id": correlation_id,
                "reason": str(e)[:200],  # Truncate long messages
                "resolved": False,
            }
        )
        db["recent_events"] = recent_events

        # Only activate panic if threshold exceeded
        if len(recent_exceptions) + 1 >= EXCEPTION_PANIC_THRESHOLD:
            db["panic_mode"] = True
            logger.warning(
                f"PANIC MODE ACTIVATED: {len(recent_exceptions) + 1} exceptions in {EXCEPTION_WINDOW_SECONDS}s"
            )
        else:
            logger.warning(
                f"Exception {len(recent_exceptions) + 1}/{EXCEPTION_PANIC_THRESHOLD} (window: {EXCEPTION_WINDOW_SECONDS}s)"
            )

        save_security_db(db)
    except Exception as persistence_error:
        logger.error(f"Failed to persist panic event: {persistence_error}")


async def panic_catcher_middleware(
    request: Request, call_next: Callable[[Request], Coroutine[None, None, Response]]
) -> Response:
    """Global exception handler that triggers Panic Mode."""
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

        # 4. Log Critical Panic
        log_panic(
            correlation_id=correlation_id,
            reason=str(e),
            payload_hash=payload_hash,
            actor=actor_snippet,
            traceback_str=traceback.format_exc(),
        )

        # 5. Persist Panic Mode (FAIL-CLOSED)
        _record_panic_event(correlation_id, e)

        # 6. Return Opaque Error
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal System Failure",
                "correlation_id": correlation_id,
                "message": "System has entered protective lockdown.",
            },
        )


def register_middlewares(app):
    """
    Register all middlewares in the correct order.
    The order here is significant because Starlette middlewares are processed as a stack.
    Requests pass through them in reverse order of registration.
    """
    app.middleware("http")(panic_mode_check_middleware)
    app.middleware("http")(allow_options_preflight_middleware)
    app.middleware("http")(correlation_id_middleware)
    app.middleware("http")(panic_catcher_middleware)
