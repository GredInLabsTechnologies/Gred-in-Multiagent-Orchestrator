import os
import time
import hashlib
import subprocess
import re
from typing import List, Optional
import shutil
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import asyncio
from contextlib import asynccontextmanager

from tools.repo_orchestrator.config import (
    BASE_DIR,
    REPO_ROOT_DIR,
    REPO_REGISTRY_PATH,
    VITAMINIZE_PACKAGE,
    MAX_LINES,
    MAX_BYTES,
    ALLOWED_EXTENSIONS,
    ALLOWLIST_REQUIRE,
    AUDIT_LOG_PATH,
    CORS_ORIGINS,
    SUBPROCESS_TIMEOUT,
    SEARCH_EXCLUDE_DIRS,
)
from tools.repo_orchestrator.security import (
    verify_token,
    validate_path,
    redact_sensitive_data,
    audit_log,
    check_rate_limit,
    load_security_db,
    save_security_db,
    load_repo_registry,
    save_repo_registry,
    get_active_repo_dir,
)

from tools.repo_orchestrator.services.git_service import GitService
from tools.repo_orchestrator.services.snapshot_service import SnapshotService
from tools.repo_orchestrator.services.system_service import SystemService

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure snapshot dir exists and start cleanup task
    SnapshotService.ensure_snapshot_dir()
    cleanup_task = asyncio.create_task(snapshot_cleanup_loop())
    yield
    # Shutdown: Cancel cleanup task
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Repo Orchestrator", version="1.0.0", lifespan=lifespan)

async def snapshot_cleanup_loop():
    """Background task to delete old snapshots every minute."""
    while True:
        try:
            await asyncio.sleep(60)
            SnapshotService.cleanup_old_snapshots()
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(10) # Avoid tight loop on errors


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

# CORS handled by middleware above to avoid preflight failures with auth

# Startup check
if not BASE_DIR.exists():
    raise RuntimeError(f"BASE_DIR {BASE_DIR} does not exist!")

start_time = time.time()

@dataclass
class RepoEntry:
    name: str
    path: str

def _list_repos() -> list[RepoEntry]:
    repos_data = GitService.list_repos(REPO_ROOT_DIR)
    return [RepoEntry(name=r["name"], path=r["path"]) for r in repos_data]

def _ensure_repo_registry(repos: list[RepoEntry]) -> dict:
    registry = load_repo_registry()
    registry_paths = {Path(r).resolve() for r in registry.get("repos", [])}
    for repo in repos:
        repo_path = Path(repo.path).resolve()
        if repo_path not in registry_paths:
            registry["repos"].append(str(repo_path))
    if registry.get("active_repo"):
        active = Path(registry["active_repo"]).resolve()
        if active not in registry_paths:
            registry["active_repo"] = str(active)
    save_repo_registry(registry)
    return registry

def _vitaminize_repo(target_repo: Path) -> list[str]:
    created = []
    for rel in VITAMINIZE_PACKAGE:
        source = BASE_DIR / rel
        dest = target_repo / rel
        if source.is_dir():
            if dest.exists():
                continue
            shutil.copytree(source, dest)
            created.append(str(dest))
        elif source.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                continue
            shutil.copy2(source, dest)
            created.append(str(dest))
    return created

class VitaminizeResponse(BaseModel):
    status: str
    created_files: list[str]
    active_repo: Optional[str] = None

class StatusResponse(BaseModel):
    version: str
    uptime_seconds: float

class UiStatusResponse(BaseModel):
    version: str
    uptime_seconds: float
    allowlist_count: int
    last_audit_line: Optional[str] = None
    service_status: str

# Helper functions
class FileWriteRequest(BaseModel):
    path: str
    content: str

def _get_service_status(service_name: str = "GILOrchestrator") -> str:
    return SystemService.get_status(service_name)

def _tail_audit_lines(limit: int = 200) -> list[str]:
    if not AUDIT_LOG_PATH.exists():
        return []
    try:
        lines = AUDIT_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
        return lines[-limit:]
    except Exception:
        return []

# Routes
@app.get("/status", response_model=StatusResponse)
async def get_status(token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    return {
        "version": "1.0.0",
        "uptime_seconds": time.time() - start_time
    }

@app.get("/ui/status", response_model=UiStatusResponse)
async def get_ui_status(request: Request, token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    audit_lines = _tail_audit_lines(limit=1)
    base_dir = get_active_repo_dir()
    allowed_paths = get_allowed_paths(base_dir) if ALLOWLIST_REQUIRE else {}
    
    # Real Integrity Check
    is_healthy = base_dir.exists() and os.access(base_dir, os.R_OK)
    status_str = "RUNNING" if is_healthy else "DEGRADED"
    
    # Agent detection for the dashboard
    user_agent = request.headers.get("User-Agent", "").lower()
    agent_label = "ChatGPT" if "openai" in user_agent or "gpt" in user_agent else "Dashboard"
    
    return {
        "version": "1.0.0",
        "uptime_seconds": time.time() - start_time,
        "allowlist_count": len(allowed_paths),
        "last_audit_line": audit_lines[-1] if audit_lines else None,
        "service_status": f"{status_str} ({agent_label})",
    }

@app.get("/ui/audit")
async def get_ui_audit(limit: int = Query(200, ge=10, le=500), token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    return {
        "lines": _tail_audit_lines(limit=limit),
    }

@app.get("/ui/allowlist")
async def get_ui_allowlist(token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    base_dir = get_active_repo_dir()
    allowed_paths = get_allowed_paths(base_dir)
    items = serialize_allowlist(allowed_paths)
    for item in items:
        try:
            item["path"] = str(Path(item["path"]).relative_to(base_dir))
        except Exception:
            continue
    return {"paths": items}

@app.get("/ui/repos")
async def list_repos(token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    repos = _list_repos()
    registry = _ensure_repo_registry(repos)
    active_repo = registry.get("active_repo")
    return {
        "root": str(REPO_ROOT_DIR),
        "active_repo": active_repo,
        "repos": [r.__dict__ for r in repos],
    }

@app.get("/ui/repos/active")
async def get_active_repo(token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    registry = load_repo_registry()
    return {"active_repo": registry.get("active_repo")}

@app.post("/ui/repos/open")
async def open_repo(path: str = Query(...), token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    repo_path = Path(path).resolve()
    if not str(repo_path).startswith(str(REPO_ROOT_DIR)):
        raise HTTPException(status_code=400, detail="Repo fuera de la base permitida")
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repo no encontrado")
    
    # TD-004: Decoupled open_repo (Server-only/Agnostic)
    # No longer attempts to spawn GUI processes like explorer.exe
    audit_log("UI", "OPEN_REPO", str(repo_path), actor=token)
    
    return {"status": "success", "message": "Repo signaled for opening (server-agnostic)"}

@app.post("/ui/repos/select")
async def select_repo(path: str = Query(...), token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    repo_path = Path(path).resolve()
    if not str(repo_path).startswith(str(REPO_ROOT_DIR)):
        raise HTTPException(status_code=400, detail="Repo fuera de la base permitida")
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repo no encontrado")
        
    registry = load_repo_registry()
    registry["active_repo"] = str(repo_path)
    save_repo_registry(registry)
    
    audit_log("REPO", "SELECT", str(repo_path), actor=token)
    return {"status": "success", "active_repo": str(repo_path)}

@app.get("/ui/security/events")
async def get_security_events(token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    db = load_security_db()
    return {
        "panic_mode": db.get("panic_mode", False),
        "events": db.get("recent_events", [])
    }

@app.post("/ui/security/resolve")
async def resolve_security(action: str = Query(...), token: str = Depends(verify_token)):
    if action != "clear_panic":
        raise HTTPException(status_code=400, detail="Invalid action")
    
    db = load_security_db()
    db["panic_mode"] = False
    for event in db.get("recent_events", []):
        event["resolved"] = True
    save_security_db(db)
    
    audit_log("SECURITY", "PANIC_CLEARED", "SUCCESS", actor=token)
    return {"status": "panic cleared"}

@app.get("/ui/service/status")
async def get_service_status(token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    return {"status": SystemService.get_status()}

@app.post("/ui/service/restart")
async def restart_service(token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    success = SystemService.restart(actor=token)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to restart service")
    return {"status": "restarting"}

@app.post("/ui/service/stop")
async def stop_service(token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    success = SystemService.stop(actor=token)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop service")
    return {"status": "stopping"}

@app.post("/ui/repos/vitaminize", response_model=VitaminizeResponse)
async def vitaminize_repo(path: str = Query(...), token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    repo_path = Path(path).resolve()
    if not str(repo_path).startswith(str(REPO_ROOT_DIR)):
        raise HTTPException(status_code=400, detail="Repo fuera de la base permitida")
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repo no encontrado")
        
    created = _vitaminize_repo(repo_path)
    
    # Auto-activate after vitaminize
    registry = load_repo_registry()
    registry["active_repo"] = str(repo_path)
    save_repo_registry(registry)
    
    audit_log("REPO", "VITAMINIZE", str(repo_path), actor=token)
    return {
        "status": "success",
        "created_files": created,
        "active_repo": str(repo_path)
    }

@app.get("/tree")
async def get_tree(path: str = ".", max_depth: int = Query(3, le=6), token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    base_dir = get_active_repo_dir()
    target = validate_path(path, base_dir)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory.")

    if ALLOWLIST_REQUIRE:
        allowed_paths = get_allowed_paths(base_dir)
        files = []
        for allowed_path in allowed_paths:
            if str(allowed_path).startswith(str(target)):
                rel_path = allowed_path.relative_to(target)
                files.append(str(rel_path))
        return {"files": sorted(set(files)), "truncated": False}
    
    result = []
    base_parts = len(target.parts)
    for root, dirs, files in os.walk(target):
        current_path = Path(root)
        depth = len(current_path.parts) - base_parts
        if depth > max_depth: continue
        dirs[:] = [
            d for d in dirs
            if not d.startswith('.') and d not in ["node_modules", ".venv", ".git", "dist", "build", *SEARCH_EXCLUDE_DIRS]
        ]
        for f in files:
            file_path = current_path / f
            if file_path.suffix in ALLOWED_EXTENSIONS:
                result.append(str(file_path.relative_to(target)))
                if len(result) >= 2000: return {"files": result, "truncated": True}
    return {"files": result, "truncated": False}

@app.get("/file", response_class=PlainTextResponse)
async def get_file(path: str, start_line: int = Query(1, ge=1), end_line: int = Query(MAX_LINES, ge=1), token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    base_dir = get_active_repo_dir()
    target = validate_path(path, base_dir)
    if not target.is_file(): raise HTTPException(status_code=400, detail="Path is not a file.")
    if target.stat().st_size > 5 * 1024 * 1024: raise HTTPException(status_code=413, detail="File too large.")

    # Snapshot mechanism: Copy file to temporary folder
    try:
        snapshot_path = SnapshotService.create_snapshot(target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create snapshot: {str(e)}")

    try:
        with open(snapshot_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
    
    if end_line - start_line + 1 > MAX_LINES:
        end_line = start_line + MAX_LINES - 1
        truncated_marker = f"\n# ... [TRUNCATED] ...\n"
    else: truncated_marker = ""
    
    content = "".join(lines[max(0, start_line-1):end_line])
    content = redact_sensitive_data(content)
    if len(content.encode('utf-8')) > MAX_BYTES:
        content = content[:MAX_BYTES] + "\n# ... [TRUNCATED] ...\n"
    else: content += truncated_marker
    
    audit_log(path, f"{start_line}-{end_line}", hashlib.sha256(content.encode()).hexdigest(), operation="READ_SNAPSHOT", actor=token)
    return content

@app.get("/search")
async def search(q: str = Query(..., min_length=3, max_length=128), ext: Optional[str] = None, token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    base_dir = get_active_repo_dir()
    hits = []
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [
            d for d in dirs
            if not d.startswith('.') and d not in ["node_modules", ".venv", ".git", *SEARCH_EXCLUDE_DIRS]
        ]
        for f in files:
            if ext and not f.endswith(ext): continue
            file_path = Path(root) / f
            if file_path.suffix not in ALLOWED_EXTENSIONS: continue
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f_obj:
                    for i, line in enumerate(f_obj):
                        if q in line:
                            hits.append({"file": str(file_path.relative_to(base_dir)), "line": i + 1, "content": redact_sensitive_data(line.strip())})
                            if len(hits) >= 50: return {"results": hits, "truncated": True}
            except: continue
    return {"results": hits, "truncated": False}

@app.get("/diff", response_class=PlainTextResponse)
async def get_diff(base: str = "main", head: str = "HEAD", token: str = Depends(verify_token), rl: None = Depends(check_rate_limit)):
    base_dir = get_active_repo_dir()
    try:
        stdout = GitService.get_diff(base_dir, base, head)
        content = redact_sensitive_data(stdout)
        if len(content.encode('utf-8')) > MAX_BYTES: content = content[:MAX_BYTES] + "\n# ... [TRUNCATED] ...\n"
        return content
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- STATIC FILES & SPA ROUTING ---
# Ensure this is after all API routes
frontend_dist = BASE_DIR / "tools" / "orchestrator_ui" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        # Serve index.html for any route that isn't /ui/ or another API route
        # This allows React Router to handle deep links
        if full_path.startswith("ui/") or full_path.startswith("search") or full_path.startswith("status") or full_path.startswith("tree") or full_path.startswith("file") or full_path.startswith("diff"):
            raise HTTPException(status_code=404)
        
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        raise HTTPException(status_code=404)
else:
    print(f"[WARNING] Frontend dist not found at {frontend_dist}")
