from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from tools.gimo_server.security import audit_log, check_rate_limit, verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.ops_models import ToolEntry
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.tool_registry_service import ToolRegistryService
from .common import _require_role, _actor_label

router = APIRouter()


@router.get("/config/mcp")
async def list_mcp_servers(
    request: Request,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
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


@router.post("/config/mcp/sync", responses={400: {"description": "Bad Request"}, 404: {"description": "Not Found"}, 500: {"description": "Internal Server Error"}})
async def sync_mcp_tools(
    request: Request,
    body: dict,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
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
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "operator")
    items = ToolRegistryService.list_tools()
    audit_log("OPS", "/ops/tool-registry", str(len(items)), operation="READ", actor=_actor_label(auth))
    return {"items": [item.model_dump() for item in items], "count": len(items)}


@router.get("/tool-registry/{tool_name}", responses={404: {"description": "Not Found"}})
async def get_tool_registry_entry(
    request: Request,
    tool_name: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
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
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    payload = body.model_copy(update={"name": tool_name})
    item = ToolRegistryService.upsert_tool(payload)
    audit_log("OPS", f"/ops/tool-registry/{tool_name}", tool_name, operation="WRITE", actor=_actor_label(auth))
    return item.model_dump()


@router.delete("/tool-registry/{tool_name}", responses={404: {"description": "Not Found"}})
async def delete_tool_registry_entry(
    request: Request,
    tool_name: str,
    auth: Annotated[AuthContext, Depends(verify_token)],
    _rl: Annotated[None, Depends(check_rate_limit)],
):
    _require_role(auth, "admin")
    deleted = ToolRegistryService.delete_tool(tool_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tool not found")
    audit_log("OPS", f"/ops/tool-registry/{tool_name}", tool_name, operation="WRITE", actor=_actor_label(auth))
    return {"status": "ok", "deleted": tool_name}
