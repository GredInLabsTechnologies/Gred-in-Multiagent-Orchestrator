import os
import time
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from tools.repo_orchestrator.config import (
    BASE_DIR,
    CORS_ORIGINS,
    REPO_ROOT_DIR,
)
from tools.repo_orchestrator.services.snapshot_service import SnapshotService
from tools.repo_orchestrator.routes import register_routes
import hashlib
import uuid
import traceback
import json
from tools.repo_orchestrator.security.audit import audit_log, log_panic
from tools.repo_orchestrator.security import (
    load_security_db, 
    save_security_db
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Perform infrastructure checks and initialization without side-effects on import
    logger.info("Starting Repo Orchestrator...")
    
    if not BASE_DIR.exists():
        logger.error(f"BASE_DIR {BASE_DIR} does not exist!")
        raise RuntimeError(f"BASE_DIR {BASE_DIR} does not exist!")

    app.state.start_time = time.time()
    
    # Ensure snapshot dir exists
    SnapshotService.ensure_snapshot_dir()
    
    # Start background cleanup task
    cleanup_task = asyncio.create_task(snapshot_cleanup_loop())
    
    yield
    
    # Shutdown: Clean up resources
    logger.info("Shutting down Repo Orchestrator...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

async def snapshot_cleanup_loop():
    """Background task to delete old snapshots every minute."""
    while True:
        try:
            await asyncio.sleep(60)
            SnapshotService.cleanup_old_snapshots()
        except Exception as e:
            logger.error(f"Error in snapshot cleanup: {str(e)}")
            await asyncio.sleep(10)

app = FastAPI(
    title="Repo Orchestrator", 
    version="1.0.0", 
    lifespan=lifespan
)

@app.middleware("http")
async def panic_mode_check(request: Request, call_next):
    """Block all requests during panic mode except the resolution endpoint."""
    # Only allow resolution endpoint during panic
    if request.url.path in ["/", "/ui/security/resolve"]:
        return await call_next(request)
    
    # Use the loader from the security module so tests can patch it
    from tools.repo_orchestrator import security as security_module
    db = security_module.load_security_db()
    if db.get("panic_mode", False):
        return Response(
            status_code=503,
            content="System in LOCKDOWN. Use /ui/security/resolve to clear panic mode."
        )
    return await call_next(request)

@app.middleware("http")
async def allow_options_preflight(request: Request, call_next):
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

from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError

@app.middleware("http")
async def panic_catcher(request: Request, call_next):
    """Global exception handler that triggers Panic Mode."""
    try:
        return await call_next(request)
    except Exception as e:
        # Ignore known HTTP exceptions (logic flow controls)
        if isinstance(e, (StarletteHTTPException, RequestValidationError)):
            raise e
        # 1. Generate Correlation ID
        correlation_id = str(uuid.uuid4())
        
        # 2. Capture & Hash Payload (Never log raw payload)
        try:
            body_bytes = await request.body()
            if not body_bytes:
                payload_hash = "empty"
            else:
                payload_hash = hashlib.sha256(body_bytes).hexdigest()
        except Exception:
            payload_hash = "read_error"

        # 3. Extract Actor (Best Effort)
        auth_header = request.headers.get("Authorization", "")
        actor_snippet = auth_header[:20] + "..." if auth_header else "anonymous"

        # 4. Log Critical Panic
        log_panic(
            correlation_id=correlation_id,
            reason=str(e),
            payload_hash=payload_hash,
            actor=actor_snippet,
            traceback_str=traceback.format_exc()
        )

        # 5. Persist Panic Mode (FAIL-CLOSED)
        try:
            db = load_security_db()
            db["panic_mode"] = True
            # Add event
            db["recent_events"] = db.get("recent_events", [])
            db["recent_events"].append({
                "type": "PANIC",
                "timestamp": str(uuid.uuid4().time), # simplified, good enough
                "correlation_id": correlation_id,
                "reason": str(e),
                "resolved": False
            })
            save_security_db(db)
        except Exception:
            pass # Fail safe

        # 6. Return Opaque Error
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal System Failure", 
                "correlation_id": correlation_id,
                "message": "System has entered protective lockdown."
            }
        )

# Register all API routes
register_routes(app)

# Static Files & SPA Routing
frontend_dist = BASE_DIR / "tools" / "orchestrator_ui" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        # Prevent shadowing API routes (though register_routes should take precedence)
        api_prefixes = ["ui/", "search", "status", "tree", "file", "diff"]
        if any(full_path.startswith(p) for p in api_prefixes):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse(status_code=404, content={"detail": "Frontend index.html not found"})
else:
    logger.warning(f"Frontend dist not found at {frontend_dist}")
