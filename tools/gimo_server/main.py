import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from tools.gimo_server.config import ACTIONS_MAX_PAYLOAD_BYTES, BASE_DIR, DEBUG, LOG_LEVEL, get_settings
from tools.gimo_server.middlewares import register_middlewares
from tools.gimo_server.routes import register_routes
from tools.gimo_server.version import __version__
from tools.gimo_server.services.snapshot_service import SnapshotService
from tools.gimo_server.services.gics_service import GicsService
from tools.gimo_server.services.log_rotation_service import LogRotationService
from tools.gimo_server.static_app import mount_static
from tools.gimo_server.tasks import snapshot_cleanup_loop
from tools.gimo_server.ops_routes import _ACTIONS_SAFE_PUBLIC_ENDPOINTS, router as ops_router
from tools.gimo_server.routers.auth_router import router as auth_router

# Configure logging with dynamic level from env
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("orchestrator")
if DEBUG:
    logger.info("DEBUG mode enabled (LOG_LEVEL=%s)", LOG_LEVEL)



async def _integrity_recheck_loop(settings):
    """Periodic integrity verification (defense-in-depth)."""
    import sys as _sys
    import asyncio
    from tools.gimo_server.security.integrity import IntegrityVerifier
    import logging
    logger = logging.getLogger("orchestrator")
    while True:
        try:
            await asyncio.sleep(6 * 3600)
            ok, reason = IntegrityVerifier(settings).verify_manifest()
            if not ok:
                logger.critical("INTEGRITY RECHECK FAILED: %s", reason)
                _sys.exit(1)
            logger.debug("INTEGRITY RECHECK: %s", reason)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Integrity recheck loop error: %s", exc)

async def _threat_decay_loop():
    """Periodically check for threat level decay."""
    import asyncio
    from tools.gimo_server.security import save_security_db, threat_engine
    import logging
    logger = logging.getLogger("orchestrator")
    while True:
        try:
            await asyncio.sleep(30)
            if threat_engine.tick_decay():
                save_security_db()
            threat_engine.cleanup_stale_sources()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Threat decay loop error: %s", exc)

async def _ops_runs_cleanup_loop():
    import asyncio
    from tools.gimo_server.services.ops_service import OpsService
    import logging
    logger = logging.getLogger("orchestrator")
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
            raise
        except Exception as exc:
            logger.warning("OPS run cleanup loop error: %s", exc)

async def _notify_sessions_for_run(run, sessions, logger, ops_service):
    ops_service.append_log(run.id, level="INFO", msg="MCP handover notification sent")
    for session in sessions:
        try:
            msg = f"⚠ GIMO Orchestrator requires Intervention for Run {run.id}.\nObjective: {run.objective}\nPlease use gimo_resolve_handover to resolve this."
            await session.create_message(
                messages=[{"role": "user", "content": {"type": "text", "text": msg}}],
                maxTokens=500,
            )
            logger.info(f"Pushed Handover Sampling request for {run.id} to client via MCP")
        except Exception as e:
            logger.error(f"Failed to push Sampling to MCP client: {e}")
            ops_service.append_log(run.id, level="WARN", msg="MCP handover blocked: no session available")

async def _mcp_sampling_loop():
    """
    Periodically checks for Runs that are blocked waiting for human/agent review (status: blocked_handover)
    and attempts to push them to connected MCP clients via Sampling.
    """
    import asyncio
    from tools.gimo_server.mcp_server import mcp
    from tools.gimo_server.services.ops_service import OpsService
    import logging
    logger = logging.getLogger("orchestrator")
    while True:
        try:
            await asyncio.sleep(5)
            # Ensure the MCP server has at least one active connection
            sessions = list(mcp._sessions) if hasattr(mcp, "_sessions") else []
            if not sessions:
                continue  # No clients to notify
            
            # Fetch pending runs needing handover
            pending_runs = OpsService.get_runs_by_status("blocked_handover")
            for run in pending_runs:
                await _notify_sessions_for_run(run, sessions, logger, OpsService)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("MCP sampling loop error: %s", exc)

async def _shutdown_services(logger, app, hw_monitor, run_worker, tasks):
    try:
        await hw_monitor.stop_monitoring()
    except asyncio.CancelledError as exc:
        logger.debug("Hardware monitor shutdown cancelled: %s", exc)
    except Exception as exc:
        logger.debug("Hardware monitor shutdown warning: %s", exc)

    if hasattr(app.state, "gics"):
        try:
            app.state.gics.stop_daemon()
        except Exception as exc:
            logger.debug("GICS daemon shutdown warning: %s", exc)

    try:
        await run_worker.stop()
    except asyncio.CancelledError as exc:
        logger.debug("Run worker shutdown cancelled: %s", exc)
    except Exception as exc:
        logger.debug("Run worker shutdown warning: %s", exc)

    for t in tasks:
        t.cancel()

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            logger.debug("Cleanup task shutdown result: %s", type(result).__name__)

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
    gics_service.start_health_check()
    app.state.gics = gics_service
    from tools.gimo_server.services.ops_service import OpsService
    OpsService.set_gics(gics_service)

    # Initialize Security Threat Engine
    from tools.gimo_server.security import save_security_db, threat_engine
    threat_engine.clear_all()  # Start clean on boot
    save_security_db()

    # Start background cleanup tasks
    cleanup_task = asyncio.create_task(snapshot_cleanup_loop())
    from tools.gimo_server.services.ops_service import OpsService

    threat_cleanup_task = asyncio.create_task(_threat_decay_loop())

    ops_cleanup_task = asyncio.create_task(_ops_runs_cleanup_loop())
    integrity_task = asyncio.create_task(_integrity_recheck_loop(settings))

    mcp_sampling_task = asyncio.create_task(_mcp_sampling_loop())
    
    # Startup reconcile + rotation for runtime consistency
    try:
        from tools.gimo_server.services.sub_agent_manager import SubAgentManager
        await SubAgentManager.startup_reconcile()
    except Exception as exc:
        logger.warning("SubAgent startup reconcile warning: %s", exc)
    try:
        merge_wt_dir = settings.ops_data_dir / "worktrees"
        if merge_wt_dir.exists():
            import shutil
            from tools.gimo_server.services.ops_service import OpsService as _OpsServiceWt
            active_run_ids = {r.id for r in _OpsServiceWt.list_runs()
                              if r.status not in _OpsServiceWt._TERMINAL_RUN_STATUSES}
            for wt in merge_wt_dir.iterdir():
                if wt.is_dir() and wt.name not in active_run_ids:
                    shutil.rmtree(wt, ignore_errors=True)
                    logger.info("Cleaned orphan merge worktree: %s", wt.name)
    except Exception as exc:
        logger.warning("Merge worktree reconcile warning: %s", exc)
    try:
        LogRotationService.run_rotation()
    except Exception as exc:
        logger.warning("Log rotation startup warning: %s", exc)

    # ── STARTUP RUN RECONCILE ─────────────────────────────────────────
    # Pass 1: Runs in non-terminal active states that survived a restart
    # are zombies — mark them error so the operator can retry.
    # Pass 2: Child runs still pending whose parent is now terminal
    # (orphaned children) are also marked error to prevent them from
    # executing without a valid parent context.
    try:
        from tools.gimo_server.services.ops_service import OpsService as _OpsServiceReconcile
        _ZOMBIE_ACTIVE = {"running", "awaiting_subagents", "awaiting_review"}
        _TERMINAL = _OpsServiceReconcile._TERMINAL_RUN_STATUSES
        _all_runs = _OpsServiceReconcile.list_runs()
        _run_status = {_r.id: _r.status for _r in _all_runs}

        _zombie_count = 0
        for _r in _all_runs:
            if _r.status in _ZOMBIE_ACTIVE:
                _OpsServiceReconcile.update_run_status(
                    _r.id, "error",
                    msg="Interrupted by server restart (startup reconcile)"
                )
                _zombie_count += 1
            elif _r.status == "pending" and _r.parent_run_id:
                # Orphaned child: parent is terminal
                _parent_status = _run_status.get(_r.parent_run_id, "")
                if _parent_status in _TERMINAL:
                    _OpsServiceReconcile.update_run_status(
                        _r.id, "error",
                        msg=(
                            f"Orphaned child (parent {_r.parent_run_id} is "
                            f"'{_parent_status}') — startup reconcile"
                        )
                    )
                    _zombie_count += 1

        if _zombie_count:
            logger.warning(
                "Startup reconcile: marked %d zombie/orphan run(s) as error.",
                _zombie_count,
            )
    except Exception as exc:
        logger.warning("Startup run reconcile warning: %s", exc)
    # ─────────────────────────────────────────────────────────────────

    # Start the Run Worker (processes pending runs in background)
    from tools.gimo_server.services.run_worker import RunWorker

    run_worker = RunWorker()
    await run_worker.start()
    app.state.run_worker = run_worker

    # Start Hardware Monitor
    from tools.gimo_server.services.hardware_monitor_service import HardwareMonitorService
    hw_monitor = HardwareMonitorService.get_instance()
    try:
        from tools.gimo_server.services.ops_service import OpsService
        cfg = OpsService.get_config()
        if cfg.economy.hardware_thresholds:
            hw_monitor.update_thresholds(cfg.economy.hardware_thresholds)
    except Exception:
        pass
    await hw_monitor.start_monitoring()

    # Single authority initialization (runtime critical services)
    try:
        from tools.gimo_server.services.authority import ExecutionAuthority
        from tools.gimo_server.services.resource_governor import ResourceGovernor
        governor = ResourceGovernor(hw_monitor)
        ExecutionAuthority.initialize(run_worker, hw_monitor, governor)
    except RuntimeError:
        logger.debug("ExecutionAuthority already initialized")
    except Exception as exc:
        logger.warning("ExecutionAuthority init warning: %s", exc)

    yield

    # Shutdown: Clean up resources (never propagate cancellation errors to TestClient)
    logger.info("Shutting down Repo Orchestrator...")
    try:
        tasks = [cleanup_task, threat_cleanup_task, ops_cleanup_task, mcp_sampling_task, integrity_task]
        await _shutdown_services(logger, app, hw_monitor, run_worker, tasks)
        if hasattr(app.state, "run_worker"):
            delattr(app.state, "run_worker")
        try:
            from tools.gimo_server.services.authority import ExecutionAuthority
            ExecutionAuthority.reset()
        except Exception:
            pass
    except Exception as exc:
        logger.debug("Lifespan shutdown suppressed exception: %s", exc)
    except asyncio.CancelledError as exc:
        logger.debug("Lifespan shutdown cancelled: %s", exc)



def _is_actions_safe_request(request: Request, actions_safe_targets: set) -> bool:
    return (request.method.upper(), request.url.path) in actions_safe_targets

def _register_core_exception_handlers(app: FastAPI, actions_safe_targets: set):
    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
        if _is_actions_safe_request(request, actions_safe_targets):
            return JSONResponse(status_code=422, content={"detail": "Invalid request payload."})
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if _is_actions_safe_request(request, actions_safe_targets) and int(exc.status_code) >= 500:
            return JSONResponse(status_code=exc.status_code, content={"detail": "Internal error."})
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

def _register_core_routes(app: FastAPI, settings):
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
        import asyncio
        await ws.accept()
        queue = await NotificationService.subscribe()
        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    await ws.send_text(message)
                except asyncio.TimeoutError:
                    await ws.send_text('{"type":"ping"}')
        except Exception:
            pass
        finally:
            NotificationService.unsubscribe(queue)

async def _check_payload_size(request: Request):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > ACTIONS_MAX_PAYLOAD_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Payload too large."})
        except ValueError:
            pass
    body = await request.body()
    if len(body) > ACTIONS_MAX_PAYLOAD_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Payload too large."})
    return None

def _create_actions_safe_guard(actions_safe_targets: set):
    async def guard(request: Request, call_next):
        if _is_actions_safe_request(request, actions_safe_targets) and request.method.upper() in {"POST", "PUT", "PATCH"}:
            resp = await _check_payload_size(request)
            if resp: return resp
        return await call_next(request)
    return guard

async def _limited_mode_guard(request: Request, call_next):
    if getattr(request.app.state, "limited_mode", False):
        if request.url.path.startswith("/auth/cold-room/"):
            return await call_next(request)
        return JSONResponse(
            {
                "detail": "Cold Room renewal required",
                "reason": getattr(request.app.state, "limited_reason", "cold_room_renewal_required"),
                "limited_mode": True,
                "allowed": ["/auth/cold-room/status", "/auth/cold-room/info", "/auth/cold-room/activate", "/auth/cold-room/renew"],
            },
            status_code=503,
        )
    return await call_next(request)

def _register_core_middlewares(app: FastAPI, actions_safe_targets: set):
    app.middleware("http")(_limited_mode_guard)
    app.middleware("http")(_create_actions_safe_guard(actions_safe_targets))

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Repo Orchestrator", version=__version__, lifespan=lifespan)
    actions_safe_targets = {(method.upper(), path) for method, path in _ACTIONS_SAFE_PUBLIC_ENDPOINTS}
    
    _register_core_exception_handlers(app, actions_safe_targets)
    _register_core_routes(app, settings)
    register_middlewares(app)
    _register_core_middlewares(app, actions_safe_targets)

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
        host="127.0.0.1",  # nosec B104 - CLI entrypoint for local/dev use
        port=port,
        reload=DEBUG,
        log_level=LOG_LEVEL.lower(),
    )
