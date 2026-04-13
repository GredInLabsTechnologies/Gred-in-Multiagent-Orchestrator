"""Legacy /ui/* endpoints still used by compatibility surfaces.

These routes must stay thin adapters over canonical backend services.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from tools.gimo_server.models import UiStatusResponse
from tools.gimo_server.security import (
    audit_log,
    check_rate_limit,
    get_active_repo_dir,
    get_allowed_paths,
    serialize_allowlist,
    verify_token,
)
from tools.gimo_server.security.access_control import require_read_only_access
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.file_service import FileService
from tools.gimo_server.services.operator_status_service import OperatorStatusService
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.providers.service import ProviderService
from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService

logger = logging.getLogger("orchestrator.routes.legacy_ui")

ERR_OPERATOR_ADMIN_REQUIRED = "operator or admin role required"
router = APIRouter(tags=["legacy-ui"])


# ── Status / Hardware / Audit ─────────────────────────────────────────

@router.get("/ui/status", response_model=UiStatusResponse)
def get_ui_status(
    request: Request,
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    status = OperatorStatusService.get_status_snapshot(
        app_start_time=getattr(request.app.state, "start_time", None),
    )
    return {
        "version": status["backend_version"],
        "uptime_seconds": status.get("uptime_seconds", 0.0),
        "allowlist_count": status["allowlist_count"],
        "last_audit_line": status["last_audit_line"],
        "service_status": status["service_status"],
    }


@router.get("/ui/hardware")
def get_ui_hardware(
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


@router.get("/ui/audit")
def get_ui_audit(
    limit: int = Query(200, ge=10, le=500),
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    return {"lines": FileService.tail_audit_lines(limit=limit)}


@router.get("/ui/allowlist")
def get_ui_allowlist(
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
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


def _is_path_within_base(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


# ── Plan / Draft bridges ──────────────────────────────────────────────

@router.post("/ui/plan/create")
async def create_plan(
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
    except Exception:
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


@router.post("/ui/drafts/{draft_id}/reject")
def reject_draft(
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


# ── Provider bridges ─────────────────────────────────────────────────

# ── Nodes / Cost bridges ─────────────────────────────────────────────

@router.get("/ui/cost/compare")
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
