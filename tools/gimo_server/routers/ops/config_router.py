from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import (
    ProviderConfig,
    OpsConfig,
    ToolEntry,
    PolicyConfig,
    ProviderModelsCatalogResponse,
    ProviderModelInstallRequest,
    ProviderModelInstallResponse,
    ProviderValidateRequest,
    ProviderValidateResponse,
)
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.provider_catalog_service import ProviderCatalogService
from tools.gimo_server.services.tool_registry_service import ToolRegistryService
from tools.gimo_server.services.policy_service import PolicyService
from tools.gimo_server.services.codex_auth_service import CodexAuthService
from .common import _require_role, _actor_label

router = APIRouter()

@router.get("/provider", response_model=ProviderConfig)
async def get_provider(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    cfg = ProviderService.get_public_config()
    if not cfg:
        raise HTTPException(status_code=404, detail="Provider not configured")
    return cfg

@router.get("/provider/capabilities")
async def get_provider_capabilities(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    matrix = ProviderService.get_capability_matrix()
    audit_log("OPS", "/ops/provider/capabilities", str(len(matrix)), operation="READ", actor=_actor_label(auth))
    return {"items": matrix, "count": len(matrix)}

@router.put("/provider", response_model=ProviderConfig)
async def set_provider(
    request: Request,
    config: ProviderConfig,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    cfg = ProviderService.set_config(config)
    audit_log("OPS", "/ops/provider", "set", operation="WRITE", actor=_actor_label(auth))
    return ProviderService.get_public_config() or cfg

@router.get("/connectors")
async def list_connectors(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = ProviderService.list_connectors()
    audit_log("OPS", "/ops/connectors", str(data.get("count", 0)), operation="READ", actor=_actor_label(auth))
    return data

@router.get("/connectors/{connector_id}/health")
async def connector_health(
    request: Request,
    connector_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
    provider_id: str | None = None,
):
    _require_role(auth, "operator")
    try:
        data = await ProviderService.connector_health(connector_id, provider_id=provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log("OPS", f"/ops/connectors/{connector_id}/health", connector_id, operation="READ", actor=_actor_label(auth))
    return data


@router.get("/connectors/{provider_type}/models", response_model=ProviderModelsCatalogResponse)
async def get_provider_models_catalog(
    request: Request,
    provider_type: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await ProviderCatalogService.get_catalog(provider_type)
    audit_log("OPS", f"/ops/connectors/{provider_type}/models", provider_type, operation="READ", actor=_actor_label(auth))
    return data


@router.post("/connectors/{provider_type}/models/install", response_model=ProviderModelInstallResponse)
async def install_provider_model(
    request: Request,
    provider_type: str,
    body: ProviderModelInstallRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    data = await ProviderCatalogService.install_model(provider_type, body.model_id)
    audit_log(
        "OPS",
        f"/ops/connectors/{provider_type}/models/install",
        f"{provider_type}:{body.model_id}:{data.status}",
        operation="EXECUTE",
        actor=_actor_label(auth),
    )
    return data


@router.get("/connectors/{provider_type}/models/install/{job_id}", response_model=ProviderModelInstallResponse)
async def get_provider_model_install_job(
    request: Request,
    provider_type: str,
    job_id: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = ProviderCatalogService.get_install_job(provider_type, job_id)
    audit_log(
        "OPS",
        f"/ops/connectors/{provider_type}/models/install/{job_id}",
        f"{provider_type}:{job_id}:{data.status}",
        operation="READ",
        actor=_actor_label(auth),
    )
    return data


@router.post("/connectors/{provider_type}/validate", response_model=ProviderValidateResponse)
async def validate_provider_credentials(
    request: Request,
    provider_type: str,
    body: ProviderValidateRequest,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await ProviderCatalogService.validate_credentials(provider_type, body)
    audit_log(
        "OPS",
        f"/ops/connectors/{provider_type}/validate",
        f"{provider_type}:{'ok' if data.valid else 'fail'}",
        operation="READ",
        actor=_actor_label(auth),
    )
    return data


@router.post("/connectors/codex/login")
async def codex_device_login(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    data = await CodexAuthService.start_device_flow()
    audit_log("OPS", "/ops/connectors/codex/login", "auth_flow_started", operation="READ", actor=_actor_label(auth))
    return data



@router.get("/config", response_model=OpsConfig)
async def get_config(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    return OpsService.get_config()

@router.put("/config", response_model=OpsConfig)
async def set_config(
    request: Request,
    config: OpsConfig,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    OpsService.set_gics(getattr(request.app.state, "gics", None))
    result = OpsService.set_config(config)
    audit_log("OPS", "/ops/config", "set", operation="WRITE", actor=_actor_label(auth))
    return result

@router.get("/config/mcp")
async def list_mcp_servers(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    cfg = ProviderService.get_config()
    if not cfg:
        return {"servers": []}
    
    servers = []
    for name, srv_config in cfg.mcp_servers.items():
        servers.append({
            "name": name,
            "command": srv_config.command,
            "args": srv_config.args,
            "enabled": srv_config.enabled,
            "env_keys": list(srv_config.env.keys())
        })
    audit_log("OPS", "/ops/config/mcp", str(len(servers)), operation="READ", actor=_actor_label(auth))
    return {"servers": servers}

@router.post("/config/mcp/sync")
async def sync_mcp_tools(
    request: Request,
    body: dict,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    server_name = body.get("server_name")
    if not server_name:
         raise HTTPException(status_code=400, detail="server_name is required")
         
    cfg = ProviderService.get_config()
    if not cfg or server_name not in cfg.mcp_servers:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' not found")
        
    srv_config = cfg.mcp_servers[server_name]
    try:
        tools = await ToolRegistryService.sync_mcp_tools(server_name, srv_config)
        audit_log("OPS", "/ops/config/mcp/sync", f"{server_name}:{len(tools)}", operation="EXECUTE", actor=_actor_label(auth))
        return {
            "status": "ok", 
            "server": server_name, 
            "tools_discovered": len(tools),
            "tools": [t.name for t in tools]
        }
    except Exception as e:
        audit_log("OPS", "/ops/config/mcp/sync", f"{server_name}:failed", operation="EXECUTE", actor=_actor_label(auth))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tool-registry")
async def list_tool_registry(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    items = ToolRegistryService.list_tools()
    audit_log("OPS", "/ops/tool-registry", str(len(items)), operation="READ", actor=_actor_label(auth))
    return {"items": [item.model_dump() for item in items], "count": len(items)}

@router.get("/tool-registry/{tool_name}")
async def get_tool_registry_entry(
    request: Request,
    tool_name: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    item = ToolRegistryService.get_tool(tool_name)
    if item is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    audit_log("OPS", f"/ops/tool-registry/{tool_name}", tool_name, operation="READ", actor=_actor_label(auth))
    return item.model_dump()

@router.put("/tool-registry/{tool_name}")
async def upsert_tool_registry_entry(
    request: Request,
    tool_name: str,
    body: ToolEntry,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    payload = body.model_copy(update={"name": tool_name})
    item = ToolRegistryService.upsert_tool(payload)
    audit_log("OPS", f"/ops/tool-registry/{tool_name}", tool_name, operation="WRITE", actor=_actor_label(auth))
    return item.model_dump()

@router.delete("/tool-registry/{tool_name}")
async def delete_tool_registry_entry(
    request: Request,
    tool_name: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    deleted = ToolRegistryService.delete_tool(tool_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tool not found")
    audit_log("OPS", f"/ops/tool-registry/{tool_name}", tool_name, operation="WRITE", actor=_actor_label(auth))
    return {"status": "ok", "deleted": tool_name}

@router.get("/policy", response_model=PolicyConfig)
async def get_policy_config(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    cfg = PolicyService.get_config()
    audit_log("OPS", "/ops/policy", "read", operation="READ", actor=_actor_label(auth))
    return cfg

@router.put("/policy", response_model=PolicyConfig)
async def set_policy_config(
    request: Request,
    body: PolicyConfig,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    cfg = PolicyService.set_config(body)
    audit_log("OPS", "/ops/policy", "updated", operation="WRITE", actor=_actor_label(auth))
    return cfg

@router.post("/policy/decide")
async def policy_decide(
    request: Request,
    body: dict,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    tool = str(body.get("tool", "")).strip()
    context = str(body.get("context", "*")).strip() or "*"
    if not tool:
        raise HTTPException(status_code=400, detail="tool is required")
    try:
        trust_score = float(body.get("trust_score", 0.0) or 0.0)
        confidence_score = float(body.get("confidence_score", 1.0) or 1.0)
    except Exception:
        raise HTTPException(status_code=400, detail="scores must be numeric")
    decision = PolicyService.decide(tool=tool, context=context, trust_score=trust_score, confidence_score=confidence_score)
    audit_log("OPS", "/ops/policy/decide", f"{tool}:{decision.get('decision')}", operation="READ", actor=_actor_label(auth))
    return {"tool": tool, "context": context, "trust_score": trust_score, "confidence_score": confidence_score, **decision}

@router.post("/model/recommend")
async def model_recommend(
    request: Request,
    body: dict,
    auth: Annotated[AuthContext, Depends(verify_token)],
    rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    node_id = body.get("node_id", "unknown")
    node_type = body.get("node_type", "agent_task")
    config = body.get("config", {})
    state = body.get("state", {})
    
    from tools.gimo_server.ops_models import WorkflowNode
    from tools.gimo_server.services.model_router_service import ModelRouterService
    
    node = WorkflowNode(id=node_id, type=node_type, config=config)
    router_service = ModelRouterService()
    recommendation = router_service.promote_eco_mode(node, state)
    
    audit_log("OPS", "/ops/model/recommend", f"{node_id}", operation="READ", actor=_actor_label(auth))
    return recommendation
