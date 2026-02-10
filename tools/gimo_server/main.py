import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from tools.gimo_server.config import BASE_DIR, get_settings
from tools.gimo_server.middlewares import register_middlewares
from tools.gimo_server.routes import register_routes
from tools.gimo_server.version import __version__
from tools.gimo_server.services.snapshot_service import SnapshotService
from tools.gimo_server.static_app import mount_static
from tools.gimo_server.tasks import snapshot_cleanup_loop
from tools.gimo_server.ops_routes import router as ops_router

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

    # Ensure OPS storage dirs exist
    settings = get_settings()
    settings.ops_data_dir.mkdir(parents=True, exist_ok=True)
    (settings.ops_data_dir / "drafts").mkdir(parents=True, exist_ok=True)
    (settings.ops_data_dir / "approved").mkdir(parents=True, exist_ok=True)
    (settings.ops_data_dir / "runs").mkdir(parents=True, exist_ok=True)
    # provider.json template
    from tools.gimo_server.services.provider_service import ProviderService

    ProviderService.ensure_default_config()

    # Start background cleanup tasks
    cleanup_task = asyncio.create_task(snapshot_cleanup_loop())
    from tools.gimo_server.services.ops_service import OpsService

    async def ops_runs_cleanup_loop():
        while True:
            try:
                await asyncio.sleep(300)
                cleaned = OpsService.cleanup_old_runs()
                if cleaned:
                    logger.info("OPS run cleanup: removed %s old runs", cleaned)
                draft_cleaned = OpsService.cleanup_old_drafts()
                if draft_cleaned:
                    logger.info("OPS draft cleanup: removed %s old drafts", draft_cleaned)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("OPS run cleanup loop error: %s", exc)

    ops_cleanup_task = asyncio.create_task(ops_runs_cleanup_loop())

    # Start the Run Worker (processes pending runs in background)
    from tools.gimo_server.services.run_worker import RunWorker

    run_worker = RunWorker()
    await run_worker.start()

    yield

    # Shutdown: Clean up resources
    logger.info("Shutting down Repo Orchestrator...")
    await run_worker.stop()
    cleanup_task.cancel()
    ops_cleanup_task.cancel()
    try:
        await cleanup_task
        await ops_cleanup_task
    except asyncio.CancelledError:
        logger.debug("Cleanup task cancelled successfully.")
    except Exception as exc:
        logger.error(f"Cleanup task failed during shutdown: {exc}")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Repo Orchestrator", version=__version__, lifespan=lifespan)

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
    app.include_router(ops_router)

    mount_static(app)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    # Canonical default port for the orchestrator service.
    # Can be overridden for advanced setups via ORCH_PORT.
    port = int(__import__("os").environ.get("ORCH_PORT", "9325"))

    uvicorn.run(
        "tools.gimo_server.main:app",
        host="0.0.0.0",  # nosec B104 - CLI entrypoint for local/dev use
        port=port,
        reload=False,
        log_level="info",
    )
