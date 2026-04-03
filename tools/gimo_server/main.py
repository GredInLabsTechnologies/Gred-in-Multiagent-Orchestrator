import asyncio
import logging
import time
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import json as _json

from tools.gimo_server.config import ACTIONS_MAX_PAYLOAD_BYTES, BASE_DIR, DEBUG, LOG_LEVEL, get_settings
# Note: middlewares.py (module) vs middlewares/ (package) - import from the .py module
import importlib.util as _importlib_util
import os as _os
_middlewares_py_path = _os.path.join(_os.path.dirname(__file__), "middlewares.py")
_middlewares_spec = _importlib_util.spec_from_file_location("_middlewares_module", _middlewares_py_path)
_middlewares_module = _importlib_util.module_from_spec(_middlewares_spec)
_middlewares_spec.loader.exec_module(_middlewares_module)
register_middlewares = _middlewares_module.register_middlewares
from tools.gimo_server.routers.core_router import router as core_router
from tools.gimo_server.routers.legacy_ui_router import router as legacy_ui_router
from tools.gimo_server.routers.redirects import router as redirects_router
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


# Custom JSONResponse with ensure_ascii=False for proper Unicode support
class UnicodeJSONResponse(JSONResponse):
    """JSONResponse that properly encodes Unicode characters (e.g., é, ñ, 中)."""
    def render(self, content) -> bytes:
        return _json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")



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
    logger.info("Starting GIMO Orchestrator...")

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
            app.state.ready = True
            yield
            logger.info("Shutting down GIMO Orchestrator (limited mode)...")
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

    async with AsyncExitStack() as app_mcp_exit_stack:
        app.state.app_mcp_exit_stack = app_mcp_exit_stack
        # Initialize MCP facade at startup (lazy init incomplete - would break streamable HTTP)
        # TODO: Full lazy init requires refactoring streamable_http_context lifecycle
        _refresh_app_mcp_facade(app, settings)
        streamable_http_context = getattr(app.state, "app_mcp_streamable_http_context", None)
        if streamable_http_context is not None:
            await app_mcp_exit_stack.enter_async_context(streamable_http_context)

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

                active_run_ids = {
                    r.id
                    for r in _OpsServiceWt.list_runs()
                    if r.status not in _OpsServiceWt._TERMINAL_RUN_STATUSES
                }
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
                        _r.id,
                        "error",
                        msg="Interrupted by server restart (startup reconcile)",
                    )
                    _zombie_count += 1
                elif _r.status == "pending" and _r.parent_run_id:
                    # Orphaned child: parent is terminal
                    _parent_status = _run_status.get(_r.parent_run_id, "")
                    if _parent_status in _TERMINAL:
                        _OpsServiceReconcile.update_run_status(
                            _r.id,
                            "error",
                            msg=(
                                f"Orphaned child (parent {_r.parent_run_id} is "
                                f"'{_parent_status}') — startup reconcile"
                            ),
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

        # F8.1: Seed initial preset telemetry for adaptive routing
        try:
            from tools.gimo_server.services.preset_telemetry_service import PresetTelemetryService

            PresetTelemetryService.seed_initial_priors()
        except Exception as exc:
            logger.warning("Preset telemetry seed warning: %s", exc)

        app.state.ready = True
        logger.info("GIMO Orchestrator ready (lifespan complete)")
        yield

        # Shutdown: Clean up resources (never propagate cancellation errors to TestClient)
        logger.info("Shutting down GIMO Orchestrator...")
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
    """Checks if a request matches one of the 'Actions-Safe' public contract endpoints.
    
    Supports template segments like {id} or {run_id}.
    Requires exact method and exact number of path segments.
    """
    method = request.method.upper()
    path = request.url.path
    
    # Fast path: exact match (static endpoints)
    if (method, path) in actions_safe_targets:
        return True

    # Slow path: segment-based matching for dynamic paths
    path_segments = [s for s in path.split("/") if s]
    
    for target_method, target_template in actions_safe_targets:
        if target_method != method:
            continue
        if "{" not in target_template:
            continue
            
        target_segments = [s for s in target_template.split("/") if s]
        if len(path_segments) != len(target_segments):
            continue
            
        match = True
        for ps, ts in zip(path_segments, target_segments):
            if ts.startswith("{") and ts.endswith("}"):
                continue # Parametrized segment (wildcard)
            if ps != ts:
                match = False
                break
        if match:
            return True
            
    return False

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
    @app.get("/health")
    async def health_route():
        """Liveness probe for k8s / load balancers."""
        import os
        return JSONResponse({
            "status": "ok",
            "version": __version__,
            "pid": os.getpid(),
            "server": "gimo",
        })

    @app.get("/ready")
    async def readiness_route():
        """Readiness probe — only returns 200 after lifespan completes."""
        import os
        ready = getattr(app.state, "ready", False)
        if not ready:
            return JSONResponse({"status": "starting"}, status_code=503)
        return JSONResponse({
            "status": "ready",
            "version": __version__,
            "pid": os.getpid(),
            "server": "gimo",
        })

    @app.post("/ops/shutdown")
    async def shutdown_route(request: Request):
        """Graceful shutdown — only from localhost.

        Triggers uvicorn's graceful shutdown sequence:
        1. Stops accepting new connections
        2. Waits for in-flight requests to complete
        3. Runs FastAPI lifespan cleanup (stops services, cancels tasks)
        4. Properly closes listening sockets (prevents Windows zombie sockets)

        On Windows: sends CTRL_BREAK_EVENT (uvicorn handles SIGBREAK since PR #1909)
        On Unix: sends SIGINT to self

        NEVER use os._exit() — it skips socket cleanup and creates zombie
        TCP LISTEN entries on Windows that persist indefinitely.
        """
        import os, signal, asyncio, sys
        client = request.client
        if not client or client.host not in ("127.0.0.1", "::1", "localhost"):
            return JSONResponse({"error": "shutdown only from localhost"}, status_code=403)
        pid = os.getpid()
        logger.info("Graceful shutdown requested (PID %d)", pid)

        async def _trigger_graceful_shutdown():
            await asyncio.sleep(0.3)  # Let the HTTP response flush
            if sys.platform == "win32":
                # CTRL_BREAK_EVENT targets only this process group (not parent)
                # Uvicorn catches SIGBREAK on Windows for graceful shutdown
                os.kill(pid, signal.SIGBREAK)
            else:
                os.kill(pid, signal.SIGINT)

        asyncio.get_event_loop().create_task(_trigger_graceful_shutdown())
        return JSONResponse({"status": "shutting_down", "pid": pid})

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
            if resp:
                return resp
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


def _refresh_app_mcp_facade(app: FastAPI, settings) -> None:
    from tools.gimo_server.app_mcp.server import create_official_app_facade

    app_mcp, official_facade, streamable_http_context = create_official_app_facade(
        profile=settings.app_mcp_profile,
        enable_streamable_http=settings.app_mcp_streamable_http,
    )

    official_mount = next((route for route in app.routes if getattr(route, "path", None) == "/mcp/app"), None)
    if official_mount is None:
        raise RuntimeError("Official App façade mount /mcp/app is missing")

    official_mount.app = official_facade
    app.state.app_mcp = app_mcp
    app.state.app_mcp_streamable_http_context = streamable_http_context
    app.state.app_mcp_profile = settings.app_mcp_profile
    app.state.app_mcp_streamable_http = settings.app_mcp_streamable_http

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="GIMO Orchestrator",
        version=__version__,
        lifespan=lifespan,
        default_response_class=UnicodeJSONResponse,  # Fix P2-7: proper Unicode encoding
    )
    actions_safe_targets = {(method.upper(), path) for method, path in _ACTIONS_SAFE_PUBLIC_ENDPOINTS}
    
    _register_core_exception_handlers(app, actions_safe_targets)
    _register_core_routes(app, settings)
    register_middlewares(app)
    _register_core_middlewares(app, actions_safe_targets)

    # Mount FastMCP servers.
    try:
        # Mount the official App façade before the legacy bridge so `/mcp/app/*`
        # does not get shadowed by the broader `/mcp` mount prefix.
        from tools.gimo_server.app_mcp.server import create_official_app_facade

        app_mcp, official_facade, streamable_http_context = create_official_app_facade(
            profile=settings.app_mcp_profile,
            enable_streamable_http=settings.app_mcp_streamable_http,
        )
        app.mount("/mcp/app", official_facade)
        app.state.app_mcp = app_mcp
        app.state.app_mcp_streamable_http_context = streamable_http_context
        app.state.app_mcp_profile = settings.app_mcp_profile
        app.state.app_mcp_streamable_http = settings.app_mcp_streamable_http
        logger.info(
            "Official App façade mounted at /mcp/app (profile=%s, streamable_http=%s)",
            settings.app_mcp_profile,
            settings.app_mcp_streamable_http,
        )

        from tools.gimo_server.mcp_server import mcp as legacy_mcp
        if legacy_mcp:
            # [LEGACY/GENERAL BRIDGE] - Not the official App façade.
            app.mount("/mcp", legacy_mcp.sse_app())
            logger.info("General MCP Bridge mounted at /mcp [LEGACY]")
    except Exception as e:
        logger.error(f"Failed to mount FastMCP Server: {e}")

    # Register all API routes
    app.include_router(core_router)
    app.include_router(legacy_ui_router)
    app.include_router(redirects_router)
    app.include_router(auth_router)
    app.include_router(ops_router)

    # Phase 3 migrated routers (direct mount — they carry their own /ops/* prefix)
    from tools.gimo_server.routers.ops.file_router import router as file_router
    from tools.gimo_server.routers.ops.repo_router import router as repo_router
    from tools.gimo_server.routers.ops.graph_router import router as graph_router
    from tools.gimo_server.routers.ops.ui_security_router import router as sec_router
    from tools.gimo_server.routers.ops.service_router import router as svc_router
    from tools.gimo_server.routers.ops.ide_context_router import router as ide_context_router
    from tools.gimo_server.routers.ops.checkpoint_router import router as checkpoint_router
    app.include_router(file_router)
    app.include_router(repo_router)
    app.include_router(graph_router)
    app.include_router(sec_router)
    app.include_router(svc_router)
    app.include_router(ide_context_router)
    app.include_router(checkpoint_router)

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
