import logging
import os
import time
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.responses import RedirectResponse

from tools.gimo_server.config import ALLOWLIST_REQUIRE
from tools.gimo_server.models import StatusResponse, UiStatusResponse
from tools.gimo_server.security import (
    audit_log,
    check_rate_limit,
    get_active_repo_dir,
    get_allowed_paths,
    serialize_allowlist,
    verify_token,
)
from tools.gimo_server.security.auth import AuthContext, SESSION_COOKIE_NAME, session_store
from tools.gimo_server.services.file_service import FileService
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService
from tools.gimo_server.version import __version__

READ_ONLY_ACTIONS_PATHS = {
    "/file",
    "/tree",
    "/search",
    "/diff",
    "/ui/status",
    "/ui/repos",
    "/ui/repos/active",
    "/ui/repos/select",
    "/ops/plan",
    "/ops/drafts",
    "/ops/approved",
    "/ops/runs",
    "/ops/config",
}

OPERATOR_EXTRA_PREFIXES = (
    "/ops/",
)

OPERATOR_EMERGENCY_PATHS = {
    "/ui/security/events",
    "/ui/security/resolve",
    "/ui/repos/revoke",
}


def _is_actions_allowed_path(path: str) -> bool:
    if path in READ_ONLY_ACTIONS_PATHS:
        return True
    if path.startswith("/ops/drafts/"):
        return True
    if path.startswith("/ops/approved/"):
        return True
    if path.startswith("/ops/runs/"):
        return True
    return False


def _is_operator_allowed_path(path: str) -> bool:
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

ERR_OPERATOR_ADMIN_REQUIRED = "operator or admin role required"
ERR_ADMIN_REQUIRED = "admin role or higher required"
ERR_PROVIDER_MISSING = "Provider config missing"
ERR_PROVIDER_NOT_FOUND = "Provider not found"


# ── Core status endpoints ──────────────────────────────────────────────

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
    import shutil
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
    return {"lines": FileService.tail_audit_lines(limit=limit)}


def _is_path_within_base(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


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
                logger.warning("Rejected allowlist path outside base %s: %s", base_dir, item.get("path"))
                continue
            item["path"] = str(resolved.relative_to(base_dir))
            safe_items.append(item)
        except (ValueError, TypeError, OSError) as exc:
            logger.warning("Failed to relativize allowlist path %s: %s", item.get("path"), exc)
            continue
    return {"paths": safe_items}


# ── Legacy UI bridge endpoints ─────────────────────────────────────────

async def create_plan_handler(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    if auth.role not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail=ERR_OPERATOR_ADMIN_REQUIRED)

    body = await request.json()
    prompt = str(body.get("prompt") or body.get("instructions") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    from tools.gimo_server.ops_models import OpsPlan, OpsTask, AgentProfile

    workspace = str(body.get("workspace") or ".")

    try:
        response = await ProviderService.static_generate(
            prompt=f"You are a multi-agent orchestration planner. Given a task, produce a JSON plan.\n\nTask: {prompt}",
            context={"task_type": "planning"}
        )
        raw = response.get("content", "{}")
        import re as _re
        json_match = _re.search(r'\{.*\}', raw, _re.DOTALL)
        plan_json = json_match.group(0) if json_match else raw
        plan_data = OpsPlan.model_validate_json(plan_json)
    except Exception as _plan_err:
        import uuid
        from datetime import datetime, timezone
        plan_data = OpsPlan(
            id=f"plan_{uuid.uuid4().hex[:8]}",
            title=prompt[:80],
            workspace=workspace,
            created=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            objective=prompt,
            tasks=[
                OpsTask(id="t1", title="Orquestador", scope="bridge", description=prompt, depends=[], status="pending",
                        agent_assignee=AgentProfile(role="orchestrator", goal="Coordinate the plan", model="qwen2.5-coder:32b",
                                                     system_prompt=f"You are the orchestrator for: {prompt}")),
                OpsTask(id="t2", title="Worker", scope="file_write", description=f"Execute: {prompt}", depends=["t1"], status="pending",
                        agent_assignee=AgentProfile(role="worker", goal=prompt, model="qwen2.5-coder:32b",
                                                     system_prompt=f"You are a specialist worker. Your task: {prompt}")),
            ]
        )

    lines = ["graph TD"]
    for task in plan_data.tasks:
        node_id = task.id.replace("-", "_")
        label = f'"{task.title}<br/>[{task.status}]"'
        lines.append(f"    {node_id}[{label}]")
        for dep in task.depends:
            lines.append(f"    {dep.replace('-', '_')} --> {node_id}")
    graph = "\n".join(lines)

    canonical_plan = TaskDescriptorService.canonicalize_plan_data(plan_data)
    draft = OpsService.create_draft(
        prompt=prompt,
        content=TaskDescriptorService.canonicalize_plan_content(canonical_plan),
        context={"structured": True, "mermaid": graph},
        provider="ui_plan_builder"
    )
    audit_log("UI", "PLAN_CREATE", draft.id, actor=auth.token)
    return {"id": draft.id, "status": draft.status, "prompt": draft.prompt, "content": draft.content, "mermaid": graph}


def reject_draft_handler(
    draft_id: str,
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
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
    cfg = ProviderService.get_public_config()
    if not cfg:
        return []
    result = []
    for pid, entry in cfg.providers.items():
        caps = entry.capabilities or {}
        provider_type = entry.provider_type or entry.type
        result.append({
            "id": pid, "type": provider_type,
            "is_local": not bool(caps.get("requires_remote_api", True)),
            "config": {"display_name": entry.display_name, "base_url": entry.base_url, "model": entry.model, "capabilities": caps},
            "deprecated": True, "deprecation_note": "Use /ops/provider as canonical source.",
        })
    return result


def add_ui_provider_bridge(
    body: dict,
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    from tools.gimo_server.ops_models import ProviderEntry, ProviderConfig

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
        type=raw_type, provider_type=canonical_type, display_name=body.get("display_name") or provider_id,
        base_url=base_url, api_key=body.get("api_key"), model=model,
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
    cfg = ProviderService.get_config()
    if not cfg or provider_id not in cfg.providers:
        raise HTTPException(status_code=404, detail=ERR_PROVIDER_NOT_FOUND)
    healthy = await ProviderService.health_check() if provider_id == cfg.active else True
    return {"status": "ok" if healthy else "error", "message": "Provider reachable" if healthy else "Provider unreachable", "deprecated": True}


def list_ui_nodes_bridge(
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
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


# ── Legacy 308 redirects ──────────────────────────────────────────────

def _redirect(new_path: str):
    async def handler(request: Request, **kw):
        qs = str(request.url.query)
        target = new_path + (f"?{qs}" if qs else "")
        return RedirectResponse(url=target, status_code=308, headers={"Deprecation": "true"})
    return handler


# ── Route registration ────────────────────────────────────────────────

def register_routes(app: FastAPI):
    # Core endpoints
    app.get("/status", response_model=StatusResponse)(get_status_handler)
    app.get("/health/deep")(get_health_deep_handler)
    app.get("/me")(get_me_handler)
    app.get("/ui/status", response_model=UiStatusResponse)(get_ui_status_handler)
    app.get("/ui/hardware")(get_ui_hardware_handler)
    app.get("/ui/audit")(get_ui_audit_handler)
    app.get("/ui/allowlist")(get_ui_allowlist_handler)

    # Legacy 308 redirects → new /ops/* routers
    app.get("/ui/repos")(_redirect("/ops/repos"))
    app.post("/ui/repos/register")(_redirect("/ops/repos/register"))
    app.get("/ui/repos/active")(_redirect("/ops/repos/active"))
    app.post("/ui/repos/open")(_redirect("/ops/repos/open"))
    app.post("/ui/repos/select")(_redirect("/ops/repos/select"))
    app.post("/ui/repos/revoke")(_redirect("/ops/repos/revoke"))
    app.get("/ui/graph")(_redirect("/ops/graph"))
    app.get("/ui/security/events")(_redirect("/ops/security/events"))
    app.post("/ui/security/resolve")(_redirect("/ops/security/resolve"))
    app.get("/ui/service/status")(_redirect("/ops/service/status"))
    app.post("/ui/service/restart")(_redirect("/ops/service/restart"))
    app.post("/ui/service/stop")(_redirect("/ops/service/stop"))
    app.post("/ui/repos/vitaminize")(_redirect("/ops/repos/vitaminize"))
    app.get("/tree")(_redirect("/ops/files/tree"))
    app.get("/file")(_redirect("/ops/files/content"))
    app.get("/search")(_redirect("/ops/files/search"))
    app.get("/diff")(_redirect("/ops/files/diff"))

    # Legacy UI bridge endpoints (to be migrated in P2)
    app.post("/ui/plan/create")(create_plan_handler)
    app.post("/ui/drafts/{draft_id}/reject")(reject_draft_handler)
    app.get("/ui/providers")(list_ui_providers_bridge)
    app.post("/ui/providers")(add_ui_provider_bridge)
    app.delete("/ui/providers/{provider_id}")(remove_ui_provider_bridge)
    app.post("/ui/providers/{provider_id}/test")(test_ui_provider_bridge)
    app.get("/ui/nodes")(list_ui_nodes_bridge)
    app.get("/ui/cost/compare")(compare_costs)
