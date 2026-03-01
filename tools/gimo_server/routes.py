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
from tools.gimo_server.services.ops_service import OpsService
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


def _overlay_run_status(nodes: list, run) -> None:
    """Update node statuses based on run logs (which tasks completed/failed)."""
    completed_tasks = set()
    running_task = None
    for entry in (run.log or []):
        msg = entry.get("msg", "")
        # Detect completed tasks from log messages
        if "✅" in msg or "delegation noted" in msg:
            for node in nodes:
                if node["id"] in msg or node["data"].get("label", "") in msg:
                    completed_tasks.add(node["id"])
        if "Executing Task" in msg:
            for node in nodes:
                if node["id"] in msg:
                    running_task = node["id"]

    for node in nodes:
        nid = node["id"]
        if run.status == "done":
            node["data"]["status"] = "done"
        elif run.status == "error":
            if nid in completed_tasks:
                node["data"]["status"] = "done"
            elif nid == running_task:
                node["data"]["status"] = "error"
            else:
                node["data"]["status"] = "pending"
        elif run.status == "running":
            if nid in completed_tasks:
                node["data"]["status"] = "done"
            elif nid == running_task:
                node["data"]["status"] = "running"
            else:
                node["data"]["status"] = "pending"
        elif run.status == "pending":
            node["data"]["status"] = "pending"


def get_ui_graph_handler(
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    """Generate dynamic graph structure for the UI based on active engines."""
    # Find most recent active engine
    engine = None
    if _WORKFLOW_ENGINES:
        # Get the move recent one (insertion order in python 3.7+)
        engine = list(_WORKFLOW_ENGINES.values())[-1]

    if not engine:
        # Priority 0: Active CustomPlans (running or draft) — unified plan system
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

        # Priority 1: Active runs (pending/running) — show live execution
        runs = []
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

        # Priority 2: Pending drafts — new plan awaiting approval
        try:
            drafts = OpsService.list_drafts()
            pending_drafts = [d for d in drafts if d.context.get("structured") and d.status == "draft" and d.content]
            if pending_drafts:
                latest = pending_drafts[0]
                nodes, edges = build_graph_from_ops_plan(latest.content, draft_id=latest.id)
                return {"nodes": nodes, "edges": edges}
        except Exception:
            pass

        # Priority 3: Most recent completed/errored run — post-execution view
        try:
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

        # Priority 4: Approved drafts waiting for run
        try:
            approved_drafts = [d for d in drafts if d.context.get("structured") and d.status == "approved" and d.content]
            if approved_drafts:
                latest = approved_drafts[0]
                nodes, edges = build_graph_from_ops_plan(latest.content, draft_id=latest.id)
                return {"nodes": nodes, "edges": edges}
        except Exception:
            pass

        return {"nodes": [], "edges": []}

    graph = engine.graph
    state_data = engine.state.data
    node_confidence = state_data.get("node_confidence", {})

    nodes = []
    for node in graph.nodes:
        # Map WorkflowNode to UI GraphNode format
        confidence = node_confidence.get(node.id)
        
        # Determine status
        status = "pending"
        # Check checkpoints for status
        for cp in reversed(engine.state.checkpoints):
            if cp.node_id == node.id:
                status = cp.status if cp.status != "completed" else "done"
                break
        
        # If it's paused due to doubt
        if state_data.get("execution_paused") and state_data.get("pause_reason") == "agent_doubt":
            # Check if this node is the one that paused
            # We don't have a direct 'current_node' but we have _resume_from_node_id
            if getattr(engine, "_resume_from_node_id", None) == node.id:
                status = "doubt"

        # Map questions if any
        pending_questions = []
        if confidence and confidence.get("questions"):
            for i, q in enumerate(confidence["questions"]):
                pending_questions.append({
                    "id": f"doubt_{node.id}_{i}",
                    "question": q,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "pending"
                })

        nodes.append({
            "id": node.id,
            "type": "orchestrator" if node.type == "agent_task" else "bridge",
            "data": {
                "label": node.config.get("label", node.id),
                "status": status,
                "confidence": confidence,
                "pendingQuestions": pending_questions,
                "trustLevel": state_data.get(f"trust_{node.id}", "autonomous"),
            },
            "position": {"x": 0, "y": 0} # Frontend layouting usually handles this, or we can mock
        })

    edges = []
    for edge in graph.edges:
        edges.append({
            "id": f"e-{edge.from_node}-{edge.to_node}",
            "source": edge.from_node,
            "target": edge.to_node,
            "animated": True
        })

    return {"nodes": nodes, "edges": edges}


def list_repos_handler(
    auth: AuthContext = Depends(require_read_only_access), rl: None = Depends(check_rate_limit)
):
    repos = RepoService.list_repos()
    registry = load_repo_registry()
    
    current_paths = set(str(Path(p).resolve()) for p in registry.get("repos", []))
    changed = False
    new_repos_list = list(registry.get("repos", []))
    
    for r in repos:
        try:
            rp = str(Path(r.path).resolve())
            if rp not in current_paths:
                new_repos_list.append(rp)
                current_paths.add(rp)
                changed = True
        except ValueError:
            pass

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
    app.get("/ui/graph")(get_ui_graph_handler)

    @app.post("/ui/plan/create")
    async def create_plan_handler(
        request: Request,
        auth: AuthContext = Depends(require_read_only_access),
        rl: None = Depends(check_rate_limit),
    ):
        """Creates a structured plan from UI and returns it as a draft."""
        if auth.role not in ("operator", "admin"):
            raise HTTPException(status_code=403, detail="operator or admin role required")

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

    @app.post("/ui/drafts/{draft_id}/reject")
    async def reject_draft_handler(
        draft_id: str,
        auth: AuthContext = Depends(require_read_only_access),
        rl: None = Depends(check_rate_limit),
    ):
        """Rejects a draft plan."""
        if auth.role not in ("operator", "admin"):
            raise HTTPException(status_code=403, detail="operator or admin role required")

        draft = OpsService.get_draft(draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        OpsService.update_draft(draft_id, status="rejected")
        audit_log("UI", "PLAN_REJECT", draft_id, actor=auth.token)
        return {"status": "rejected", "id": draft_id}

    @app.get("/ui/providers")
    async def list_ui_providers_bridge(
        auth: AuthContext = Depends(require_read_only_access),
        rl: None = Depends(check_rate_limit),
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

    @app.post("/ui/providers")
    async def add_ui_provider_bridge(
        body: dict,
        auth: AuthContext = Depends(require_read_only_access),
        rl: None = Depends(check_rate_limit),
    ):
        from tools.gimo_server.ops_models import ProviderEntry, ProviderConfig
        from tools.gimo_server.services.provider_service import ProviderService

        if auth.role != "admin":
            raise HTTPException(status_code=403, detail="admin role or higher required")

        cfg = ProviderService.get_config()
        if not cfg:
            raise HTTPException(status_code=404, detail="Provider config missing")

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

    @app.delete("/ui/providers/{provider_id}")
    async def remove_ui_provider_bridge(
        provider_id: str,
        auth: AuthContext = Depends(require_read_only_access),
        rl: None = Depends(check_rate_limit),
    ):
        from tools.gimo_server.ops_models import ProviderConfig
        from tools.gimo_server.services.provider_service import ProviderService

        if auth.role != "admin":
            raise HTTPException(status_code=403, detail="admin role or higher required")

        cfg = ProviderService.get_config()
        if not cfg:
            raise HTTPException(status_code=404, detail="Provider config missing")
        if provider_id not in cfg.providers:
            raise HTTPException(status_code=404, detail="Provider not found")

        cfg.providers.pop(provider_id, None)
        if not cfg.providers:
            raise HTTPException(status_code=400, detail="At least one provider is required")
        if cfg.active == provider_id:
            cfg.active = next(iter(cfg.providers.keys()))
        ProviderService.set_config(ProviderConfig(active=cfg.active, providers=cfg.providers, mcp_servers=cfg.mcp_servers))
        audit_log("UI", "LEGACY_PROVIDER_REMOVE", provider_id, actor=f"{auth.role}:legacy_bridge")
        return {"status": "removed", "id": provider_id, "deprecated": True}

    @app.post("/ui/providers/{provider_id}/test")
    async def test_ui_provider_bridge(
        provider_id: str,
        auth: AuthContext = Depends(require_read_only_access),
        rl: None = Depends(check_rate_limit),
    ):
        from tools.gimo_server.services.provider_service import ProviderService

        cfg = ProviderService.get_config()
        if not cfg or provider_id not in cfg.providers:
            raise HTTPException(status_code=404, detail="Provider not found")

        healthy = await ProviderService.health_check() if provider_id == cfg.active else True
        return {
            "status": "ok" if healthy else "error",
            "message": "Provider reachable" if healthy else "Provider unreachable",
            "deprecated": True,
        }

    @app.get("/ui/nodes")
    async def list_ui_nodes_bridge(
        auth: AuthContext = Depends(require_read_only_access),
        rl: None = Depends(check_rate_limit),
    ):
        """Bridge endpoint kept for legacy UI compatibility."""
        return {}
    
    @app.get("/ui/cost/compare")
    async def compare_costs(
        model_a: str = Query(..., min_length=1),
        model_b: str = Query(..., min_length=1),
        auth: AuthContext = Depends(verify_token),
    ):
        from tools.gimo_server.services.cost_service import CostService
        try:
            return CostService.get_impact_comparison(model_a, model_b)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

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
