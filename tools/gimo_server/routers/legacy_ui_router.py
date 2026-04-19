"""Legacy /ui/* endpoints — UNMOUNTED shim, kept for reference.

# DEPRECATED: this router is not included in main.py and has no live callers.
# The canonical equivalents are live under /ops/* (see docs/CLIENT_SURFACES.md
# §Parity Closure). This file is preserved because:
#   1. The /ui/* URL pattern is documented as a legacy surface; if anyone mounts
#      this router in the future, the handlers below already delegate to the
#      canonical OperatorStatusService (audit F2 fix applied preventively).
#   2. Removing the file would violate the "reconnect, don't delete" principle
#      from AGENTS.md §12 without a verified-replacement audit of every handler.
#
# Sunset criterion: once docs/CLIENT_SURFACES.md removes /ui/* from the topology
# and no external documentation references the URL, delete this file in a
# dedicated commit with a 30-day notice in the changelog.
#
# Owner: surface-parity team.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from tools.gimo_server.config import ALLOWLIST_REQUIRE
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
from tools.gimo_server.services.ops import OpsService
from tools.gimo_server.services.providers.service import ProviderService
from tools.gimo_server.services.task_descriptor_service import TaskDescriptorService
from tools.gimo_server.version import __version__

logger = logging.getLogger("orchestrator.routes.legacy_ui")

ERR_OPERATOR_ADMIN_REQUIRED = "operator or admin role required"
ERR_ADMIN_REQUIRED = "admin role or higher required"
ERR_PROVIDER_MISSING = "Provider config missing"
ERR_PROVIDER_NOT_FOUND = "Provider not found"

router = APIRouter(tags=["legacy-ui"])


# ── Status / Hardware / Audit ─────────────────────────────────────────

@router.get("/ui/status", response_model=UiStatusResponse)
def get_ui_status(
    request: Request,
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    """Legacy /ui/status ingress. Delegates to the canonical OperatorStatusService.

    DEPRECATED: the canonical endpoint is /ops/operator/status. This handler
    remains as a thin compatibility shim for clients that have not migrated
    (audit finding F2 — surface authority drift). No domain logic is computed
    locally; all authoritative fields come from the canonical service.

    Sunset criterion: when all documented clients migrate to /ops/operator/status.
    Owner: surface-parity team.
    """
    from tools.gimo_server.services.operator_status_service import OperatorStatusService
    snapshot = OperatorStatusService.ui_status_snapshot(app_start_time=request.app.state.start_time)
    # Surface-specific presentation: annotate the canonical status with the
    # calling UA. This is a render concern, not domain state — kept local.
    user_agent = request.headers.get("User-Agent", "").lower()
    agent_label = "ChatGPT" if "openai" in user_agent or "gpt" in user_agent else "Dashboard"
    return {
        "version": __version__,
        "uptime_seconds": snapshot.get("uptime_seconds", time.time() - request.app.state.start_time),
        "allowlist_count": snapshot.get("allowlist_count", 0),
        "last_audit_line": snapshot.get("last_audit_line"),
        "service_status": f"{snapshot.get('service_status', 'UNKNOWN')} ({agent_label})",
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

@router.get("/ui/providers")
def list_ui_providers(
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


@router.post("/ui/providers")
def add_ui_provider(
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


@router.delete("/ui/providers/{provider_id}")
def remove_ui_provider(
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


@router.post("/ui/providers/{provider_id}/test")
async def test_ui_provider(
    provider_id: str,
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    cfg = ProviderService.get_config()
    if not cfg or provider_id not in cfg.providers:
        raise HTTPException(status_code=404, detail=ERR_PROVIDER_NOT_FOUND)
    healthy = await ProviderService.health_check() if provider_id == cfg.active else True
    return {"status": "ok" if healthy else "error", "message": "Provider reachable" if healthy else "Provider unreachable", "deprecated": True}


# ── Nodes / Cost bridges ─────────────────────────────────────────────

@router.get("/ui/nodes")
def list_ui_nodes(
    auth: Annotated[AuthContext, Depends(require_read_only_access)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    return {}


@router.get("/ui/cost/compare")
def compare_costs(
    model_a: Annotated[str, Query(..., min_length=1)],
    model_b: Annotated[str, Query(..., min_length=1)],
    auth: Annotated[AuthContext, Depends(verify_token)],
):
    from tools.gimo_server.services.economy.cost_service import CostService
    try:
        return CostService.get_impact_comparison(model_a, model_b)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
