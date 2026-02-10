import logging

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from tools.gimo_server.config import BASE_DIR

logger = logging.getLogger("orchestrator")


def mount_static(app):
    # Static Files & SPA Routing
    frontend_dist = BASE_DIR / "tools" / "orchestrator_ui" / "dist"
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(request: Request, full_path: str):
            # Prevent shadowing API routes (though register_routes should take precedence)
            api_prefixes = ["ui/", "search", "status", "tree", "file", "diff", "ops/"]
            if any(full_path.startswith(p) for p in api_prefixes):
                return JSONResponse(status_code=404, content={"detail": "Not Found"})

            index_file = frontend_dist / "index.html"
            if index_file.exists():
                return FileResponse(str(index_file))
            return JSONResponse(
                status_code=404, content={"detail": "Frontend index.html not found"}
            )

    else:
        logger.warning(f"Frontend dist not found at {frontend_dist}")
