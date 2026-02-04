import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from tools.repo_orchestrator.config import BASE_DIR, get_settings
from tools.repo_orchestrator.middlewares import register_middlewares
from tools.repo_orchestrator.routes import register_routes
from tools.repo_orchestrator.services.snapshot_service import SnapshotService
from tools.repo_orchestrator.static_app import mount_static
from tools.repo_orchestrator.tasks import snapshot_cleanup_loop

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
        logger.debug("Cleanup task cancelled successfully.")
    except Exception as exc:
        logger.error(f"Cleanup task failed during shutdown: {exc}")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Repo Orchestrator", version="1.0.0", lifespan=lifespan)

    @app.get("/")
    async def root_route():
        """Serve the SPA index when available, otherwise return a basic health payload."""
        frontend_dist = settings.base_dir / "tools" / "orchestrator_ui" / "dist"
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse({"status": "ok"})

    register_middlewares(app)

    # Register all API routes
    register_routes(app)

    mount_static(app)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "tools.repo_orchestrator.main:app",
        host="0.0.0.0",  # nosec B104 - CLI entrypoint for local/dev use
        port=6834,
        reload=False,
        log_level="info",
    )
