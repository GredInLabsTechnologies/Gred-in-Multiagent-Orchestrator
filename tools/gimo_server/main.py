import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from tools.gimo_server.config import BASE_DIR, DEBUG, LOG_LEVEL, get_settings
from tools.gimo_server.middlewares import register_middlewares
from tools.gimo_server.routes import register_routes
from tools.gimo_server.version import __version__
from tools.gimo_server.services.snapshot_service import SnapshotService
from tools.gimo_server.services.gics_service import GicsService
from tools.gimo_server.static_app import mount_static
from tools.gimo_server.tasks import snapshot_cleanup_loop
from tools.gimo_server.ops_routes import router as ops_router
from tools.gimo_server.routers.auth_router import router as auth_router

# Configure logging with dynamic level from env
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("orchestrator")
if DEBUG:
    logger.info("DEBUG mode enabled (LOG_LEVEL=%s)", LOG_LEVEL)


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
    app.state.limited_mode = False
    app.state.limited_reason = ""

    # ── RUNTIME GUARD + INTEGRITY (pre-license hardening) ─────────────
    import sys as _sys
    from tools.gimo_server.security.runtime_guard import RuntimeGuard
    from tools.gimo_server.security.integrity import IntegrityVerifier

    _runtime_report = RuntimeGuard(settings).evaluate()
    app.state.runtime_guard_report = {
        "debugger_detected": _runtime_report.debugger_detected,
        "vm_detected": _runtime_report.vm_detected,
        "vm_indicators": _runtime_report.vm_indicators,
        "blocked": _runtime_report.blocked,
        "reasons": _runtime_report.reasons,
    }
    if _runtime_report.blocked:
        logger.critical("RUNTIME GUARD BLOCKED STARTUP: %s", ",".join(_runtime_report.reasons))
        _sys.exit(1)

    _integrity_ok, _integrity_reason = IntegrityVerifier(settings).verify_manifest()
    if not _integrity_ok:
        logger.critical("INTEGRITY CHECK FAILED: %s", _integrity_reason)
        _sys.exit(1)
    logger.info("INTEGRITY: %s", _integrity_reason)

    async def integrity_recheck_loop():
        """Periodic integrity verification (defense-in-depth)."""
        while True:
            try:
                await asyncio.sleep(6 * 3600)
                ok, reason = IntegrityVerifier(settings).verify_manifest()
                if not ok:
                    logger.critical("INTEGRITY RECHECK FAILED: %s", reason)
                    _sys.exit(1)
                logger.debug("INTEGRITY RECHECK: %s", reason)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Integrity recheck loop error: %s", exc)

    # ── LICENSE GATE ──────────────────────────────────────────────────
    # Must pass before ANY other service starts.
    from tools.gimo_server.security.license_guard import LicenseGuard
    _guard = LicenseGuard(settings)
    _license_status = await _guard.validate()
    if not _license_status.valid:
        if settings.cold_room_enabled and _license_status.reason == "cold_room_renewal_required":
            app.state.limited_mode = True
            app.state.limited_reason = _license_status.reason
            app.state.license_guard = _guard
            logger.warning("=" * 60)
            logger.warning("  LIMITED MODE ENABLED (Cold Room renewal required)")
            logger.warning("  Reason: %s", _license_status.reason)
            logger.warning("  Only /auth/cold-room/* endpoints are available")
            logger.warning("=" * 60)
            yield
            logger.info("Shutting down Repo Orchestrator (limited mode)...")
            return
        logger.critical("=" * 60)
        logger.critical("  LICENSE VALIDATION FAILED")
        logger.critical("  Reason: %s", _license_status.reason)
        logger.critical("  Get your license at https://gimo-web.vercel.app")
        logger.critical("=" * 60)
        _sys.exit(1)
    logger.info("LICENSE: Valid (plan=%s)", _license_status.plan)
    app.state.license_guard = _guard
    # Re-validate in background every 24h
    import asyncio as _asyncio
    _asyncio.create_task(_guard.periodic_recheck())
    # ──────────────────────────────────────────────────────────────────

    settings.ops_data_dir.mkdir(parents=True, exist_ok=True)
    (settings.ops_data_dir / "drafts").mkdir(parents=True, exist_ok=True)
    (settings.ops_data_dir / "approved").mkdir(parents=True, exist_ok=True)
    (settings.ops_data_dir / "runs").mkdir(parents=True, exist_ok=True)
    (settings.ops_data_dir / "threads").mkdir(parents=True, exist_ok=True)
    # provider.json template
    from tools.gimo_server.services.provider_service import ProviderService

    ProviderService.ensure_default_config()
    
    # Initialize GICS Daemon Service
    gics_service = GicsService()
    gics_service.start_daemon()
    app.state.gics = gics_service

    # Initialize Security Threat Engine
    from tools.gimo_server.security import save_security_db, threat_engine
    threat_engine.clear_all()  # Start clean on boot
    save_security_db()

    # Start background cleanup tasks
    cleanup_task = asyncio.create_task(snapshot_cleanup_loop())
    from tools.gimo_server.services.ops_service import OpsService

    async def threat_decay_loop():
        """Periodically check for threat level decay."""
        while True:
            try:
                await asyncio.sleep(30)
                if threat_engine.tick_decay():
                    save_security_db()
                threat_engine.cleanup_stale_sources()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Threat decay loop error: %s", exc)

    threat_cleanup_task = asyncio.create_task(threat_decay_loop())

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
    integrity_task = asyncio.create_task(integrity_recheck_loop())

    async def mcp_sampling_loop():
        """
        Periodically checks for Runs that are blocked waiting for human/agent review (status: blocked_handover)
        and attempts to push them to connected MCP clients via Sampling.
        """
        while True:
            try:
                await asyncio.sleep(5)
                # Ensure the MCP server has at least one active connection
                from tools.gimo_server.mcp_server import mcp
                
                # Check for handovers if clients are connected
                from tools.gimo_server.services.ops_service import OpsService
                from mcp.types import CreateMessageRequestParams
                # Getting recently blocked runs 
                # (For simplicity in this POC we query 'blocked_handover' directly from ops dir)
                # FastMCP provides access to sessions
                sessions = list(mcp._sessions) if hasattr(mcp, "_sessions") else []
                
                if not sessions:
                    continue  # No clients to notify
                
                # Fetch pending runs needing handover
                pending_runs = OpsService.get_runs_by_status("blocked_handover")
                
                for run in pending_runs:
                    # Mark as 'notifying_handover' temporarily so we don't spam
                    OpsService.update_run_status(run.id, "notifying_handover")
                    
                    for session in sessions:
                        try:
                            # Send Sampling Push Notification to Client
                            msg = f"⚠ GIMO Orchestrator requires Intervention for Run {run.id}.\nObjective: {run.objective}\nPlease use gimo_resolve_handover to resolve this."
                            
                            await session.create_message(
                                messages=[
                                    {
                                        "role": "user", 
                                        "content": {
                                            "type": "text", 
                                            "text": msg
                                        }
                                    }
                                ],
                                maxTokens=500,
                            )
                            logger.info(f"Pushed Handover Sampling request for {run.id} to client via MCP")
                        except Exception as e:
                            logger.error(f"Failed to push Sampling to MCP client: {e}")
                            OpsService.update_run_status(run.id, "blocked_handover") # rollback

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("MCP sampling loop error: %s", exc)
                
    mcp_sampling_task = asyncio.create_task(mcp_sampling_loop())
    
    # Start the Run Worker (processes pending runs in background)
    from tools.gimo_server.services.run_worker import RunWorker

    run_worker = RunWorker()
    await run_worker.start()

    yield

    # Shutdown: Clean up resources
    logger.info("Shutting down Repo Orchestrator...")
    if hasattr(app.state, "gics"):
        app.state.gics.stop_daemon()
    await run_worker.stop()
    cleanup_task.cancel()
    threat_cleanup_task.cancel()
    ops_cleanup_task.cancel()
    mcp_sampling_task.cancel()
    integrity_task.cancel()
    
    try:
        await cleanup_task
        await threat_cleanup_task
        await ops_cleanup_task
        await mcp_sampling_task
        await integrity_task
    except asyncio.CancelledError:
        logger.debug("Cleanup tasks cancelled successfully.")
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

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        """Real-time event stream via WebSocket (mirrors /ops/stream SSE)."""
        from tools.gimo_server.services.notification_service import NotificationService
        await ws.accept()
        queue = await NotificationService.subscribe()
        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    await ws.send_text(message)
                except asyncio.TimeoutError:
                    await ws.send_text('{"type":"ping"}')
        except (WebSocketDisconnect, Exception):
            pass
        finally:
            NotificationService.unsubscribe(queue)

    register_middlewares(app)

    @app.middleware("http")
    async def limited_mode_guard(request, call_next):
        if getattr(app.state, "limited_mode", False):
            if request.url.path.startswith("/auth/cold-room/"):
                return await call_next(request)
            return JSONResponse(
                {
                    "detail": "Cold Room renewal required",
                    "reason": getattr(app.state, "limited_reason", "cold_room_renewal_required"),
                    "limited_mode": True,
                    "allowed": ["/auth/cold-room/status", "/auth/cold-room/info", "/auth/cold-room/activate", "/auth/cold-room/renew"],
                },
                status_code=503,
            )
        return await call_next(request)

    # Mount FastMCP SSE Server
    try:
        from tools.gimo_server.mcp_server import mcp
        app.mount("/mcp", mcp.sse_app())
        logger.info("Universal MCP Server mounted at /mcp")
    except Exception as e:
        logger.error(f"Failed to mount FastMCP Server: {e}")

    # Register all API routes
    register_routes(app)
    app.include_router(auth_router)
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
        reload=DEBUG,
        log_level=LOG_LEVEL.lower(),
    )
