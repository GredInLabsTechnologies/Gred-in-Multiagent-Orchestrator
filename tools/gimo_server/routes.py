import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from tools.gimo_server.config import ALLOWLIST_REQUIRE, MAX_LINES, REPO_ROOT_DIR
from tools.gimo_server.models import StatusResponse, UiStatusResponse, VitaminizeResponse
from tools.gimo_server.security import (
    audit_log,
    check_rate_limit,
    get_active_repo_dir,
    get_allowed_paths,
    load_repo_registry,
    load_security_db,
    save_repo_registry,
    save_security_db,
    serialize_allowlist,
    validate_path,
    verify_token,
)
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.file_service import FileService
from tools.gimo_server.services.repo_service import RepoService
from tools.gimo_server.services.system_service import SystemService
from tools.gimo_server.version import __version__

READ_ONLY_ACTIONS_PATHS = {
    "/file",
    "/tree",
    "/search",
    "/diff",
    "/ui/status",
    # OPS v2 read endpoints (prefix-matched via helper)
    "/ops/plan",
    "/ops/drafts",
    "/ops/approved",
    "/ops/runs",
    "/ops/config",
}

# Operator can access everything actions can PLUS OPS mutation paths.
# Fine-grained method+role checks happen inside ops_routes via _require_role.
OPERATOR_EXTRA_PREFIXES = (
    "/ops/",
)


# Operator/admin emergency endpoints.
OPERATOR_EMERGENCY_PATHS = {
    "/ui/security/events",
    "/ui/security/resolve",
}


def _is_actions_allowed_path(path: str) -> bool:
    """Return True if the read-only (actions) token may access this path."""
    if path in READ_ONLY_ACTIONS_PATHS:
        return True

    # Allow detail endpoints for OPS (but NOT provider endpoints).
    if path.startswith("/ops/drafts/"):
        return True
    if path.startswith("/ops/approved/"):
        return True
    if path.startswith("/ops/runs/"):
        return True
    return False


def _is_operator_allowed_path(path: str) -> bool:
    """Return True if the operator token may access this path.

    Operator gets all actions paths plus all /ops/* paths.
    The per-endpoint role checks in ops_routes enforce what the operator
    can actually *do* (approve, run, but not change provider/plan).
    """
    if _is_actions_allowed_path(path):
        return True

    if path in OPERATOR_EMERGENCY_PATHS:
        return True
    for prefix in OPERATOR_EXTRA_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def require_read_only_access(
    request: Request, auth: AuthContext = Depends(verify_token)
) -> AuthContext:
    path = request.url.path
    if auth.role == "actions":
        if not _is_actions_allowed_path(path):
            raise HTTPException(
                status_code=403, detail="Read-only token cannot access this endpoint"
            )
    elif auth.role == "operator":
        if not _is_operator_allowed_path(path):
            raise HTTPException(
                status_code=403, detail="Operator token cannot access this endpoint"
            )
    return auth


logger = logging.getLogger("orchestrator.routes")

# Constants for error messages
ERR_REPO_NOT_FOUND = "Repo no encontrado"
ERR_REPO_OUT_OF_BASE = "Repo fuera de la base permitida"

# Route Handlers


def get_status_handler(
    request: Request,
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    return {"version": __version__, "uptime_seconds": time.time() - request.app.state.start_time}


def get_ui_status_handler(
    request: Request,
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    audit_lines = FileService.tail_audit_lines(limit=1)
    base_dir = get_active_repo_dir()
    allowed_paths = get_allowed_paths(base_dir) if ALLOWLIST_REQUIRE else {}

    is_healthy = base_dir.exists() and os.access(base_dir, os.R_OK)
    status_str = "RUNNING" if is_healthy else "DEGRADED"

    user_agent = request.headers.get("User-Agent", "").lower()
    agent_label = "ChatGPT" if "openai" in user_agent or "gpt" in user_agent else "Dashboard"

    return {
        "version": __version__,
        "uptime_seconds": time.time() - request.app.state.start_time,
        "allowlist_count": len(allowed_paths),
        "last_audit_line": audit_lines[-1] if audit_lines else None,
        "service_status": f"{status_str} ({agent_label})",
    }


def get_ui_audit_handler(
    limit: int = Query(200, ge=10, le=500),
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    return {
        "lines": FileService.tail_audit_lines(limit=limit),
    }


def get_ui_allowlist_handler(
    auth: AuthContext = Depends(require_read_only_access), rl: None = Depends(check_rate_limit)
):
    base_dir = get_active_repo_dir()
    allowed_paths = get_allowed_paths(base_dir)
    items = serialize_allowlist(allowed_paths)
    safe_items = []
    for item in items:
        try:
            resolved = Path(item["path"]).resolve()
            if not _is_path_within_base(resolved, base_dir):
                logger.warning(
                    "Rejected allowlist path outside base %s: %s",
                    base_dir,
                    item.get("path"),
                )
                continue
            item["path"] = str(resolved.relative_to(base_dir))
            safe_items.append(item)
        except (ValueError, TypeError, OSError) as exc:
            logger.warning("Failed to relativize allowlist path %s: %s", item.get("path"), exc)
            continue
    return {"paths": safe_items}


def list_repos_handler(
    auth: AuthContext = Depends(require_read_only_access), rl: None = Depends(check_rate_limit)
):
    repos = RepoService.list_repos()
    registry = RepoService.ensure_repo_registry(repos)
    active_repo = registry.get("active_repo")

    # Sanitize paths to prevent information disclosure
    def sanitize_path(path_str: str) -> str:
        """Remove user-specific portions from paths."""
        if not path_str:
            return path_str
        # Replace Windows user paths (raw string for proper escaping)
        path_str = re.sub(r"C:\\Users\\[^\\]+", r"C:\\Users\\[USER]", path_str)
        # Replace Unix home paths
        path_str = re.sub(r"/home/[^/]+", "/home/[USER]", path_str)
        path_str = re.sub(r"/Users/[^/]+", "/Users/[USER]", path_str)
        return path_str

    return {
        "root": sanitize_path(str(REPO_ROOT_DIR)),
        "active_repo": sanitize_path(active_repo) if active_repo else None,
        "repos": [{"name": r.name, "path": sanitize_path(r.path)} for r in repos],
    }


def get_active_repo_handler(
    auth: AuthContext = Depends(require_read_only_access), rl: None = Depends(check_rate_limit)
):
    registry = load_repo_registry()
    return {"active_repo": registry.get("active_repo")}


def _is_path_within_base(path: Path, base: Path) -> bool:
    """Safely check if path is within base directory."""
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def open_repo_handler(
    path: str = Query(...),
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    repo_path = Path(path).resolve()
    if not _is_path_within_base(repo_path, REPO_ROOT_DIR):
        raise HTTPException(status_code=400, detail=ERR_REPO_OUT_OF_BASE)
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail=ERR_REPO_NOT_FOUND)

    audit_log("UI", "OPEN_REPO", str(repo_path), actor=auth.token)
    return {"status": "success", "message": "Repo signaled for opening (server-agnostic)"}


def select_repo_handler(
    path: str = Query(...),
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    repo_path = Path(path).resolve()
    if not _is_path_within_base(repo_path, REPO_ROOT_DIR):
        raise HTTPException(status_code=400, detail=ERR_REPO_OUT_OF_BASE)
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail=ERR_REPO_NOT_FOUND)

    registry = load_repo_registry()
    registry["active_repo"] = str(repo_path)
    save_repo_registry(registry)

    audit_log("REPO", "SELECT", str(repo_path), actor=auth.token)
    return {"status": "success", "active_repo": str(repo_path)}


def get_security_events_handler(
    auth: AuthContext = Depends(require_read_only_access), rl: None = Depends(check_rate_limit)
):
    db = load_security_db()
    return {"panic_mode": db.get("panic_mode", False), "events": db.get("recent_events", [])}


def resolve_security_handler(
    action: str = Query(...), auth: AuthContext = Depends(require_read_only_access)
):
    if action != "clear_panic":
        raise HTTPException(status_code=400, detail="Invalid action")

    db = load_security_db()
    db["panic_mode"] = False
    for event in db.get("recent_events", []):
        event["resolved"] = True
    save_security_db(db)

    audit_log("SECURITY", "PANIC_CLEARED", "SUCCESS", actor=auth.token)
    return {"status": "panic cleared"}


def get_service_status_handler(
    auth: AuthContext = Depends(require_read_only_access), rl: None = Depends(check_rate_limit)
):
    return {"status": SystemService.get_status()}


def restart_service_handler(
    auth: AuthContext = Depends(require_read_only_access), rl: None = Depends(check_rate_limit)
):
    success = SystemService.restart(actor=auth.token)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to restart service")
    return {"status": "restarting"}


def stop_service_handler(
    auth: AuthContext = Depends(require_read_only_access), rl: None = Depends(check_rate_limit)
):
    success = SystemService.stop(actor=auth.token)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop service")
    return {"status": "stopping"}


def vitaminize_repo_handler(
    path: str = Query(...),
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    repo_path = Path(path).resolve()
    if not _is_path_within_base(repo_path, REPO_ROOT_DIR):
        raise HTTPException(status_code=400, detail=ERR_REPO_OUT_OF_BASE)
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail=ERR_REPO_NOT_FOUND)

    created = RepoService.vitaminize_repo(repo_path)

    registry = load_repo_registry()
    registry["active_repo"] = str(repo_path)
    save_repo_registry(registry)

    audit_log("REPO", "VITAMINIZE", str(repo_path), actor=auth.token)
    return {"status": "success", "created_files": created, "active_repo": str(repo_path)}


async def get_tree_handler(
    path: str = ".",
    max_depth: int = Query(3, le=6),
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    base_dir = get_active_repo_dir()
    target = validate_path(path, base_dir)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory.")

    if ALLOWLIST_REQUIRE:
        allowed_paths = get_allowed_paths(base_dir)
        files = []
        for p in allowed_paths:
            try:
                rel = p.resolve().relative_to(target.resolve())
            except ValueError:
                continue
            files.append(str(rel))
        return {"files": sorted(set(files)), "truncated": False}

    import asyncio

    loop = asyncio.get_running_loop()
    files = await loop.run_in_executor(None, RepoService.walk_tree, target, max_depth)
    return {"files": files, "truncated": len(files) >= 2000}


def get_file_handler(
    path: str,
    start_line: int = Query(1, ge=1),
    end_line: int = Query(MAX_LINES, ge=1),
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    base_dir = get_active_repo_dir()
    target = validate_path(path, base_dir)
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file.")
    if target.stat().st_size > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large.")

    try:
        content, _ = FileService.get_file_content(target, start_line, end_line, auth.token)
        return content
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def search_handler(
    q: str = Query(..., min_length=3, max_length=128),
    ext: Optional[str] = None,
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    base_dir = get_active_repo_dir()
    import asyncio

    loop = asyncio.get_running_loop()
    hits = await loop.run_in_executor(None, RepoService.perform_search, base_dir, q, ext)
    return {"results": hits, "truncated": len(hits) >= 50}


def get_diff_handler(
    base: str = "main",
    head: str = "HEAD",
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    from tools.gimo_server.config import MAX_BYTES
    from tools.gimo_server.security import redact_sensitive_data
    from tools.gimo_server.services.git_service import GitService

    base_dir = get_active_repo_dir()
    try:
        stdout = GitService.get_diff(base_dir, base, head)
        content = redact_sensitive_data(stdout)
        if len(content.encode("utf-8")) > MAX_BYTES:
            content = content[:MAX_BYTES] + "\n# ... [TRUNCATED] ...\n"
        return content
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def register_routes(app: FastAPI):
    app.get("/status", response_model=StatusResponse)(get_status_handler)
    app.get("/ui/status", response_model=UiStatusResponse)(get_ui_status_handler)
    app.get("/ui/audit")(get_ui_audit_handler)
    app.get("/ui/allowlist")(get_ui_allowlist_handler)
    app.get("/ui/repos")(list_repos_handler)
    app.get("/ui/repos/active")(get_active_repo_handler)
    app.post("/ui/repos/open")(open_repo_handler)
    app.post("/ui/repos/select")(select_repo_handler)
    app.get("/ui/security/events")(get_security_events_handler)
    app.post("/ui/security/resolve")(resolve_security_handler)
    app.get("/ui/service/status")(get_service_status_handler)
    app.post("/ui/service/restart")(restart_service_handler)
    app.post("/ui/service/stop")(stop_service_handler)
    app.post("/ui/repos/vitaminize", response_model=VitaminizeResponse)(vitaminize_repo_handler)
    app.get("/tree")(get_tree_handler)
    app.get("/file", response_class=PlainTextResponse)(get_file_handler)
    app.get("/search")(search_handler)
    app.get("/diff", response_class=PlainTextResponse)(get_diff_handler)
