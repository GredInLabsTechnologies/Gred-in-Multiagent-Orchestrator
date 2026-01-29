import os
import time
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from tools.repo_orchestrator.config import (
    BASE_DIR,
    CORS_ORIGINS,
)
from tools.repo_orchestrator.services.snapshot_service import SnapshotService
from tools.repo_orchestrator.routes import register_routes

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
    await cleanup_task

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
