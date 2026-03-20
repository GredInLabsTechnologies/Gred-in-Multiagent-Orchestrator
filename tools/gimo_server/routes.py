import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Optional, Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from tools.gimo_server.config import ALLOWLIST_REQUIRE, MAX_LINES, REPO_ROOT_DIR
from tools.gimo_server.models import StatusResponse, UiStatusResponse, VitaminizeResponse
from tools.gimo_server.security import (
    audit_log,
    check_rate_limit,
    get_active_repo_dir,
    get_allowed_paths,
    load_repo_registry,
    save_repo_registry,
    serialize_allowlist,
    validate_path,
    verify_token,
)
from tools.gimo_server.security.auth import AuthContext, SESSION_COOKIE_NAME, session_store
from tools.gimo_server.services.file_service import FileService
from tools.gimo_server.services.repo_service import RepoService
from tools.gimo_server.services.repo_override_service import RepoOverrideService
from tools.gimo_server.services.system_service import SystemService
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.plan_graph_builder import build_graph_from_ops_plan
from tools.gimo_server.routers.ops.common import _WORKFLOW_ENGINES
from tools.gimo_server.version import __version__
from datetime import datetime, timezone

READ_ONLY_ACTIONS_PATHS = {
    "/file",
    "/tree",
    "/search",
    "/diff",
    "/ui/status",
    "/ui/repos",
    "/ui/repos/active",
    "/ui/repos/select",
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
    "/ui/repos/revoke",
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
    elif auth.role == "operator" and not _is_operator_allowed_path(path):
        raise HTTPException(
            status_code=403, detail="Operator token cannot access this endpoint"
        )
    return auth


logger = logging.getLogger("orchestrator.routes")

# Constants for error messages
ERR_REPO_NOT_FOUND = "Repo no encontrado"
ERR_REPO_OUT_OF_BASE = "Repo fuera de la base permitida"
ERR_OPERATOR_ADMIN_REQUIRED = "operator or admin role required"
ERR_ADMIN_REQUIRED = "admin role or higher required"
ERR_PROVIDER_MISSING = "Provider config missing"
ERR_PROVIDER_NOT_FOUND = "Provider not found"

# Route Handlers


def get_status_handler(
    request: Request,
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    return {"version": __version__, "uptime_seconds": time.time() - request.app.state.start_time}


async def get_health_deep_handler(
    request: Request,
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    uptime_seconds = time.time() - request.app.state.start_time
    ops_dir = OpsService.OPS_DIR
    try:
        disk_total_bytes, _disk_used_bytes, disk_free_bytes = shutil.disk_usage(ops_dir)
    except Exception:
        disk_free_bytes = None
        disk_total_bytes = None

    provider_ok = await ProviderService.health_check()

    return {
        "status": "ok" if provider_ok else "degraded",
        "version": __version__,
        "uptime_seconds": uptime_seconds,
        "checks": {
            "ops_dir_exists": ops_dir.exists(),
            "provider_health": provider_ok,
            "gics_attached": bool(getattr(request.app.state, "gics", None)),
            "run_worker_attached": bool(getattr(request.app.state, "run_worker", None)),
        },
        "storage": {
            "ops_dir": str(ops_dir),
            "disk_free_bytes": disk_free_bytes,
            "disk_total_bytes": disk_total_bytes,
        },
    }


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


def get_ui_hardware_handler(
    request: Request,
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    from tools.gimo_server.services.hardware_monitor_service import HardwareMonitorService
    from tools.gimo_server.services.model_inventory_service import ModelInventoryService

    hw = HardwareMonitorService.get_instance()
    state = hw.get_current_state()
    models = ModelInventoryService.get_available_models()
    state["available_models"] = len(models)
    state["local_models"] = len([m for m in models if getattr(m, "is_local", False)])
    state["remote_models"] = len([m for m in models if not getattr(m, "is_local", False)])
    state["local_safe"] = hw.is_local_safe()
    return state


def get_me_handler(request: Request):
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_value:
        raise HTTPException(status_code=401, detail="Session missing")
    session = session_store.validate(cookie_value)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")
    return {
        "email": session.email,
        "displayName": session.display_name,
        "plan": session.plan,
        "firebaseUser": bool(session.firebase_user),
        "role": session.role,
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


def _is_node_completed(msg: str, n_id: str, lbl: str) -> bool:
    if "✅" in msg or "delegation noted" in msg:
        if n_id in msg or (lbl and lbl in msg):
            return True
    return False

def _parse_run_logs_for_status(nodes: list, logs: list):
    completed = set()
    running = None

    for entry in logs:
        msg = entry.get("msg", "")
        for n in nodes:
            n_id = n["id"]
            lbl = n["data"].get("label", "")
            if _is_node_completed(msg, n_id, lbl):
                completed.add(n_id)
        if "Executing Task" in msg:
            for n in nodes:
                if n["id"] in msg:
                    running = n["id"]
    return completed, running

def _apply_node_status(node, run_status, completed_tasks, running_task):
    nid = node["id"]
    if run_status == "done":
        return "done"
    elif run_status == "pending":
        return "pending"
    
    # "error" or "running"
    if nid in completed_tasks:
        return "done"
    elif nid == running_task:
        return run_status
    return "pending"

def _overlay_run_status(nodes: list, run) -> None:
    """Update node statuses based on run logs (which tasks completed/failed)."""
    logs = run.log or []
    completed_tasks, running_task = _parse_run_logs_for_status(nodes, logs)
    
    for node in nodes:
        node["data"]["status"] = _apply_node_status(node, run.status, completed_tasks, running_task)


def _get_graph_for_custom_plan():
    try:
        from tools.gimo_server.services.custom_plan_service import CustomPlanService
        all_plans = CustomPlanService.list_plans()
        active_cp = next((p for p in all_plans if p.status in ("running", "draft")), None)
        if active_cp and active_cp.nodes:
            cp_nodes = []
            cp_edges = []
            for node in active_cp.nodes:
                cp_nodes.append({
                    "id": node.id,
                    "type": "custom",
                    "position": {"x": node.position.x, "y": node.position.y},
                    "data": {
                        "label": node.label,
                        "status": node.status,
                        "node_type": node.node_type,
                        "role": node.role,
                        "model": node.model,
                        "provider": node.provider,
                        "prompt": node.prompt,
                        "role_definition": node.role_definition,
                        "is_orchestrator": node.is_orchestrator,
                        "output": node.output,
                        "error": node.error,
                        "plan": {"draft_id": active_cp.id},
                        "custom_plan_id": active_cp.id,
                    },
                })
            for edge in active_cp.edges:
                cp_edges.append({
                    "id": edge.id,
                    "source": edge.source,
                    "target": edge.target,
                })
            return {"nodes": cp_nodes, "edges": cp_edges}
    except Exception:
        pass
    return None

def _get_graph_for_active_runs():
    try:
        runs = OpsService.list_runs()
        active_runs = [r for r in runs if r.status in ("pending", "running")]
        if active_runs:
            latest_run = active_runs[0]
            approved = OpsService.get_approved(latest_run.approved_id)
            if approved and approved.content:
                nodes, edges = build_graph_from_ops_plan(approved.content, draft_id=latest_run.id)
                _overlay_run_status(nodes, latest_run)
                return {"nodes": nodes, "edges": edges}
    except Exception:
        pass
    return None

def _get_graph_for_pending_drafts():
    try:
        drafts = OpsService.list_drafts()
        pending_drafts = [d for d in drafts if d.context.get("structured") and d.status == "draft" and d.content]
        if pending_drafts:
            latest = pending_drafts[0]
            nodes, edges = build_graph_from_ops_plan(latest.content, draft_id=latest.id)
            return {"nodes": nodes, "edges": edges}
    except Exception:
        pass
    return None

def _get_graph_for_recent_done_runs():
    try:
        runs = OpsService.list_runs()
        recent_done = [r for r in runs if r.status in ("done", "error")]
        if recent_done:
            latest_done = recent_done[0]
            approved = OpsService.get_approved(latest_done.approved_id)
            if approved and approved.content:
                nodes, edges = build_graph_from_ops_plan(approved.content, draft_id=latest_done.id)
                _overlay_run_status(nodes, latest_done)
                return {"nodes": nodes, "edges": edges}
    except Exception:
        pass
    return None

def _get_graph_for_approved_drafts():
    try:
        drafts = OpsService.list_drafts()
        approved_drafts = [d for d in drafts if d.context.get("structured") and d.status == "approved" and d.content]
        if approved_drafts:
            latest = approved_drafts[0]
            nodes, edges = build_graph_from_ops_plan(latest.content, draft_id=latest.id)
            return {"nodes": nodes, "edges": edges}
    except Exception:
        pass
    return None

def _process_engine_node(node, state_data, checkpoints, resume_id):
    confidence = state_data.get("node_confidence", {}).get(node.id)
    status = "pending"
    for cp in reversed(checkpoints):
        if cp.node_id == node.id:
            status = cp.status if cp.status != "completed" else "done"
            break
            
    if state_data.get("execution_paused") and state_data.get("pause_reason") == "agent_doubt":
        if resume_id == node.id:
            status = "doubt"

    pending_questions = []
    if confidence and confidence.get("questions"):
        for i, q in enumerate(confidence["questions"]):
            pending_questions.append({
                "id": f"doubt_{node.id}_{i}",
                "question": q,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "pending"
            })

    return {
        "id": node.id,
        "type": "orchestrator" if getattr(node, "type", "") == "agent_task" else "bridge",
        "data": {
            "label": getattr(node, "config", {}).get("label", node.id),
            "status": status,
            "confidence": confidence,
            "pendingQuestions": pending_questions,
            "trustLevel": state_data.get(f"trust_{node.id}", "autonomous"),
        },
        "position": {"x": 0, "y": 0}
    }

def _build_engine_graph(engine):
    graph = engine.graph
    state_data = engine.state.data
    checkpoints = engine.state.checkpoints
    resume_id = getattr(engine, "_resume_from_node_id", None)

    nodes = [_process_engine_node(node, state_data, checkpoints, resume_id) for node in graph.nodes]
    
    edges = [{
        "id": f"e-{edge.from_node}-{edge.to_node}",
        "source": edge.from_node,
        "target": edge.to_node,
        "animated": True
    } for edge in graph.edges]

    return {"nodes": nodes, "edges": edges}

def get_ui_graph_handler(
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    """Generate dynamic graph structure for the UI based on active engines."""
    engine = None
    if _WORKFLOW_ENGINES:
        engine = list(_WORKFLOW_ENGINES.values())[-1]

    if not engine:
        result = _get_graph_for_custom_plan()
        if result: return result
        
        result = _get_graph_for_active_runs()
        if result: return result
        
        result = _get_graph_for_pending_drafts()
        if result: return result
        
        result = _get_graph_for_recent_done_runs()
        if result: return result
        
        result = _get_graph_for_approved_drafts()
        if result: return result
        
        return {"nodes": [], "edges": []}

    return _build_engine_graph(engine)


def list_repos_handler(
    auth: AuthContext = Depends(require_read_only_access), rl: None = Depends(check_rate_limit)
):
    repos = RepoService.list_repos()
    registry = load_repo_registry()
    
    current_paths = {str(Path(p).resolve()) for p in registry.get("repos", [])}
    changed = False
    new_repos_list = list(registry.get("repos", []))
    
    for r in repos:
        raw_path = (r.path or "").strip()
        if not raw_path:
            continue
        try:
            rp = str(Path(raw_path).resolve())
            if rp not in current_paths:
                new_repos_list.append(rp)
                current_paths.add(rp)
                changed = True
        except ValueError:
            pass

    # Include manually registered repositories even if they are outside REPO_ROOT_DIR.
    merged_paths: set[str] = set()
    merged_repos: list[dict[str, str]] = []
    empty_path_repos: list[dict[str, str]] = []
    for r in repos:
        raw_path = (r.path or "").strip()
        if not raw_path:
            empty_path_repos.append({"name": r.name, "path": ""})
            continue
        try:
            rp = str(Path(raw_path).resolve())
            if rp not in merged_paths:
                merged_paths.add(rp)
                merged_repos.append({"name": r.name, "path": rp})
        except Exception:
            continue

    for p in registry.get("repos", []):
        try:
            resolved = Path(p).resolve()
            if not resolved.exists() or not resolved.is_dir():
                continue
            rp = str(resolved)
            if rp in merged_paths:
                continue
            merged_paths.add(rp)
            merged_repos.append({"name": resolved.name, "path": rp})
        except Exception:
            continue

    # Keep deterministic order: resolvable repositories first, placeholders last.
    merged_repos.extend(empty_path_repos)

    if changed:
        registry["repos"] = new_repos_list
        save_repo_registry(registry)

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
        "repos": [{"name": r["name"], "path": sanitize_path(r["path"])} for r in merged_repos],
    }


def register_repo_handler(
    path: str = Query(...),
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    repo_path = Path(path).resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise HTTPException(status_code=404, detail=ERR_REPO_NOT_FOUND)

    registry = load_repo_registry()
    repos = list(registry.get("repos", []))
    rp = str(repo_path)
    if rp not in repos:
        repos.append(rp)
        registry["repos"] = repos
        save_repo_registry(registry)

    audit_log("REPO", "REGISTER", rp, actor=auth.token)
    return {"status": "success", "path": rp}


def get_active_repo_handler(
    auth: AuthContext = Depends(require_read_only_access), rl: None = Depends(check_rate_limit)
):
    override = RepoOverrideService.get_active_override()
    if override:
        payload = {
            "active_repo": override.get("repo_id"),
            "override_active": True,
            "etag": override.get("etag"),
            "expires_at": override.get("expires_at"),
            "set_by_user": override.get("set_by_user"),
        }
        return JSONResponse(payload, headers={"ETag": str(override.get("etag", ""))})

    registry = load_repo_registry()
    return {
        "active_repo": registry.get("active_repo"),
        "override_active": False,
        "etag": None,
        "expires_at": None,
        "set_by_user": None,
    }


def _is_path_within_base(path: Path, base: Path) -> bool:
    """Safely check if path is within base directory."""
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _is_registered_repo_path(path: Path) -> bool:
    try:
        registry = load_repo_registry()
        registered = {str(Path(p).resolve()) for p in registry.get("repos", [])}
        return str(path.resolve()) in registered
    except Exception:
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
    request: Request = None,
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    repo_path = Path(path).resolve()
    if not _is_path_within_base(repo_path, REPO_ROOT_DIR) and not _is_registered_repo_path(repo_path):
        raise HTTPException(status_code=400, detail=ERR_REPO_OUT_OF_BASE)
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail=ERR_REPO_NOT_FOUND)

    override = RepoOverrideService.get_active_override()
    if auth.role == "actions" and override:
        audit_log(
            "REPO_OVERRIDE",
            "BLOCK_ACTIONS",
            str(repo_path),
            operation="repo_override_blocked_actions",
            actor=auth.token,
        )
        raise HTTPException(status_code=403, detail="REPO_OVERRIDE_ACTIVE")

    if_match_etag = request.headers.get("if-match") if request else None
    try:
        new_override = RepoOverrideService.set_human_override(
            repo_id=str(repo_path),
            set_by_user=auth.token,
            source="api",
            reason="manual_select",
            if_match_etag=if_match_etag,
        )
    except ValueError as exc:
        if str(exc) == "OVERRIDE_ETAG_MISMATCH":
            raise HTTPException(status_code=409, detail="OVERRIDE_ETAG_MISMATCH")
        raise

    registry = load_repo_registry()
    registry["active_repo"] = str(repo_path)
    save_repo_registry(registry)

    audit_log("REPO", "SELECT", str(repo_path), actor=auth.token)
    return {
        "status": "success",
        "active_repo": str(repo_path),
        "override_active": True,
        "etag": new_override.get("etag"),
        "expires_at": new_override.get("expires_at"),
    }


def revoke_repo_override_handler(
    request: Request,
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    if auth.role not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail=ERR_OPERATOR_ADMIN_REQUIRED)

    if_match_etag = request.headers.get("if-match")
    try:
        revoked = RepoOverrideService.revoke_human_override(
            actor=auth.token,
            if_match_etag=if_match_etag,
        )
    except ValueError as exc:
        if str(exc) == "OVERRIDE_ETAG_MISMATCH":
            raise HTTPException(status_code=409, detail="OVERRIDE_ETAG_MISMATCH")
        raise

    return {"status": "success" if revoked else "noop", "revoked": revoked}


def resolve_security_handler(
    request: Request,
    action: str = "clear_all",  # "clear_all" or "downgrade"
    auth: AuthContext = Depends(verify_token),
):
    """
    Manually resolve or downgrade security threat level.
    Requires valid authentication.
    """
    from tools.gimo_server.security import save_security_db, threat_engine

    # Only operator/admin can manually clear threats
    if auth.role not in ["operator", "admin"]:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only operators can manually resolve security threats."
        )

    if action == "clear_all":
        threat_engine.clear_all()
    elif action == "downgrade":
        threat_engine.downgrade()
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    # Persist the change
    save_security_db()

    return {
        "status": "success",
        "action": action,
        "new_level": threat_engine.level_label,
        "message": f"Threat level set to {threat_engine.level_label}"
    }


def get_security_events_handler(_auth: AuthContext = Depends(verify_token)):
    """
    Get detailed security status and recent events.
    """
    from tools.gimo_server.security import threat_engine
    return threat_engine.snapshot()


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
    if not _is_path_within_base(repo_path, REPO_ROOT_DIR) and not _is_registered_repo_path(repo_path):
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


async def create_plan_handler(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Creates a structured plan from UI and returns it as a draft."""
    if auth.role not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail=ERR_OPERATOR_ADMIN_REQUIRED)

    body = await request.json()
    prompt = str(body.get("prompt") or body.get("instructions") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    from tools.gimo_server.services.provider_service import ProviderService
    from tools.gimo_server.ops_models import OpsPlan

    workspace = str(body.get("workspace") or ".")

    # Generate structured plan via LLM
    system_msg = (
        "You are a multi-agent orchestration planner. Given a task, produce a JSON plan with "
        "the schema: {\"id\": \"plan_xxx\", \"title\": \"Short plan title\", "
        "\"workspace\": \".\", \"created\": \"2026-01-01\", \"objective\": \"...\", "
        "\"tasks\": [{\"id\": \"t1\", \"title\": \"...\", \"scope\": \"bridge\", "
        "\"description\": \"...\", \"depends\": [], \"status\": \"pending\", "
        "\"agent_assignee\": {\"role\": \"orchestrator\", \"goal\": \"...\", \"model\": \"qwen2.5-coder:32b\", "
        "\"system_prompt\": \"...\", \"instructions\": [\"...\"]}}, "
        "{\"id\": \"t2\", \"title\": \"...\", \"scope\": \"file_write\", "
        "\"description\": \"...\", \"depends\": [\"t1\"], \"status\": \"pending\", "
        "\"agent_assignee\": {\"role\": \"worker\", \"goal\": \"...\", \"model\": \"qwen2.5-coder:32b\", "
        "\"system_prompt\": \"...\", \"instructions\": [\"...\"]}}]}. "
        "First task is always the orchestrator (scope=bridge). Remaining tasks are workers (scope=file_write). "
        "Return ONLY valid JSON, no markdown."
    )

    try:
        response = await ProviderService.static_generate(
            prompt=f"{system_msg}\n\nTask: {prompt}",
            context={"task_type": "planning"}
        )
        raw = response.get("content", "{}")

        # Try to extract JSON from response
        import re as _re
        json_match = _re.search(r'\{.*\}', raw, _re.DOTALL)
        plan_json = json_match.group(0) if json_match else raw

        plan_data = OpsPlan.model_validate_json(plan_json)
    except Exception as _plan_err:
        # Fallback: create a simple 2-node plan
        import logging as _log
        _log.getLogger("orchestrator").warning("Plan LLM failed, using fallback: %s", _plan_err)
        import uuid
        from datetime import datetime, timezone
        from tools.gimo_server.ops_models import OpsTask, AgentProfile
        plan_data = OpsPlan(
            id=f"plan_{uuid.uuid4().hex[:8]}",
            title=prompt[:80],
            workspace=workspace,
            created=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            objective=prompt,
            tasks=[
                OpsTask(
                    id="t1", title="Orquestador", scope="bridge",
                    description=prompt, depends=[], status="pending",
                    agent_assignee=AgentProfile(
                        role="orchestrator", goal="Coordinate the plan",
                        model="qwen2.5-coder:32b",
                        system_prompt=f"You are the orchestrator for: {prompt}",
                    )
                ),
                OpsTask(
                    id="t2", title="Worker", scope="file_write",
                    description=f"Execute: {prompt}",
                    depends=["t1"], status="pending",
                    agent_assignee=AgentProfile(
                        role="worker", goal=prompt,
                        model="qwen2.5-coder:32b",
                        system_prompt=f"You are a specialist worker. Your task: {prompt}",
                    )
                ),
            ]
        )

    # Generate mermaid graph from plan
    lines = ["graph TD"]
    for task in plan_data.tasks:
        node_id = task.id.replace("-", "_")
        label = f'"{task.title}<br/>[{task.status}]"'
        lines.append(f"    {node_id}[{label}]")
        for dep in task.depends:
            lines.append(f"    {dep.replace('-', '_')} --> {node_id}")
    graph = "\n".join(lines)

    draft = OpsService.create_draft(
        prompt=prompt,
        content=plan_data.model_dump_json(indent=2),
        context={"structured": True, "mermaid": graph},
        provider="ui_plan_builder"
    )

    audit_log("UI", "PLAN_CREATE", draft.id, actor=auth.token)
    return {
        "id": draft.id,
        "status": draft.status,
        "prompt": draft.prompt,
        "content": draft.content,
        "mermaid": graph,
    }


def reject_draft_handler(
    draft_id: str,
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Rejects a draft plan."""
    if auth.role not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail=ERR_OPERATOR_ADMIN_REQUIRED)

    draft = OpsService.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    OpsService.update_draft(draft_id, status="rejected")
    audit_log("UI", "PLAN_REJECT", draft_id, actor=auth.token)
    return {"status": "rejected", "id": draft_id}


def list_ui_providers_bridge(
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Bridge endpoint for legacy UI. Source of truth is OPS provider config."""
    from tools.gimo_server.services.provider_service import ProviderService

    cfg = ProviderService.get_public_config()
    if not cfg:
        return []

    result = []
    for pid, entry in cfg.providers.items():
        caps = entry.capabilities or {}
        provider_type = entry.provider_type or entry.type
        result.append(
            {
                "id": pid,
                "type": provider_type,
                "is_local": not bool(caps.get("requires_remote_api", True)),
                "config": {
                    "display_name": entry.display_name,
                    "base_url": entry.base_url,
                    "model": entry.model,
                    "capabilities": caps,
                },
                "deprecated": True,
                "deprecation_note": "Use /ops/provider as canonical source.",
            }
        )
    return result


def add_ui_provider_bridge(
    body: dict,
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    from tools.gimo_server.ops_models import ProviderEntry, ProviderConfig
    from tools.gimo_server.services.provider_service import ProviderService

    if auth.role != "admin":
        raise HTTPException(status_code=403, detail=ERR_ADMIN_REQUIRED)

    cfg = ProviderService.get_config()
    if not cfg:
        raise HTTPException(status_code=404, detail=ERR_PROVIDER_MISSING)

    provider_id = str(body.get("id") or body.get("name") or "").strip()
    if not provider_id:
        raise HTTPException(status_code=400, detail="provider id is required")

    raw_type = str(body.get("provider_type") or body.get("type") or "custom_openai_compatible")
    canonical_type = ProviderService.normalize_provider_type(raw_type)
    model = str(body.get("model") or body.get("default_model") or "gpt-4o-mini")
    base_url = body.get("base_url")
    if canonical_type == "ollama_local" and not base_url:
        base_url = "http://localhost:11434/v1"

    cfg.providers[provider_id] = ProviderEntry(
        type=raw_type,
        provider_type=canonical_type,
        display_name=body.get("display_name") or provider_id,
        base_url=base_url,
        api_key=body.get("api_key"),
        model=model,
        capabilities=ProviderService.capabilities_for(canonical_type),
    )

    updated = ProviderService.set_config(
        ProviderConfig(active=cfg.active if cfg.active in cfg.providers else provider_id, providers=cfg.providers, mcp_servers=cfg.mcp_servers)
    )
    audit_log("UI", "LEGACY_PROVIDER_ADD", provider_id, actor=f"{auth.role}:legacy_bridge")
    return {"id": provider_id, "status": "registered", "active": updated.active, "deprecated": True}


def remove_ui_provider_bridge(
    provider_id: str,
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    from tools.gimo_server.ops_models import ProviderConfig
    from tools.gimo_server.services.provider_service import ProviderService

    if auth.role != "admin":
        raise HTTPException(status_code=403, detail=ERR_ADMIN_REQUIRED)

    cfg = ProviderService.get_config()
    if not cfg:
        raise HTTPException(status_code=404, detail=ERR_PROVIDER_MISSING)
    if provider_id not in cfg.providers:
        raise HTTPException(status_code=404, detail=ERR_PROVIDER_NOT_FOUND)

    cfg.providers.pop(provider_id, None)
    if not cfg.providers:
        raise HTTPException(status_code=400, detail="At least one provider is required")
    if cfg.active == provider_id:
        cfg.active = next(iter(cfg.providers.keys()))
    ProviderService.set_config(ProviderConfig(active=cfg.active, providers=cfg.providers, mcp_servers=cfg.mcp_servers))
    audit_log("UI", "LEGACY_PROVIDER_REMOVE", provider_id, actor=f"{auth.role}:legacy_bridge")
    return {"status": "removed", "id": provider_id, "deprecated": True}


async def test_ui_provider_bridge(
    provider_id: str,
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    from tools.gimo_server.services.provider_service import ProviderService

    cfg = ProviderService.get_config()
    if not cfg or provider_id not in cfg.providers:
        raise HTTPException(status_code=404, detail=ERR_PROVIDER_NOT_FOUND)

    healthy = await ProviderService.health_check() if provider_id == cfg.active else True
    return {
        "status": "ok" if healthy else "error",
        "message": "Provider reachable" if healthy else "Provider unreachable",
        "deprecated": True,
    }


def list_ui_nodes_bridge(
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    """Bridge endpoint kept for legacy UI compatibility."""
    return {}


def compare_costs(
    model_a: Annotated[str, Query(..., min_length=1)],
    model_b: Annotated[str, Query(..., min_length=1)],
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    from tools.gimo_server.services.cost_service import CostService
    try:
        return CostService.get_impact_comparison(model_a, model_b)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def register_routes(app: FastAPI):
    app.get("/status", response_model=StatusResponse)(get_status_handler)
    app.get("/health/deep")(get_health_deep_handler)
    app.get("/me")(get_me_handler)
    app.get("/ui/status", response_model=UiStatusResponse)(get_ui_status_handler)
    app.get("/ui/hardware")(get_ui_hardware_handler)
    app.get("/ui/audit")(get_ui_audit_handler)
    app.get("/ui/allowlist")(get_ui_allowlist_handler)
    app.get("/ui/repos")(list_repos_handler)
    app.post("/ui/repos/register")(register_repo_handler)
    app.get("/ui/repos/active")(get_active_repo_handler)
    app.post("/ui/repos/open")(open_repo_handler)
    app.post("/ui/repos/select")(select_repo_handler)
    app.post("/ui/repos/revoke")(revoke_repo_override_handler)
    app.get("/ui/graph")(get_ui_graph_handler)
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

    app.post("/ui/plan/create", responses={403: {"description": ERR_OPERATOR_ADMIN_REQUIRED}, 400: {"description": "prompt is required"}})(create_plan_handler)
    app.post("/ui/drafts/{draft_id}/reject", responses={403: {"description": ERR_OPERATOR_ADMIN_REQUIRED}, 404: {"description": "Draft not found"}})(reject_draft_handler)
    app.get("/ui/providers")(list_ui_providers_bridge)
    app.post("/ui/providers", responses={403: {"description": ERR_ADMIN_REQUIRED}, 404: {"description": ERR_PROVIDER_MISSING}, 400: {"description": "provider id is required"}})(add_ui_provider_bridge)
    app.delete("/ui/providers/{provider_id}", responses={403: {"description": ERR_ADMIN_REQUIRED}, 404: {"description": "Provider missing or not found"}, 400: {"description": "At least one provider is required"}})(remove_ui_provider_bridge)
    app.post("/ui/providers/{provider_id}/test", responses={404: {"description": ERR_PROVIDER_NOT_FOUND}})(test_ui_provider_bridge)
    app.get("/ui/nodes")(list_ui_nodes_bridge)
    app.get("/ui/cost/compare", responses={400: {"description": "Bad Request"}})(compare_costs)
