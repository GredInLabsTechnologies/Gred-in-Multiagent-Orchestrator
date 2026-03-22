import logging
import keyword
from mcp.server.fastmcp import FastMCP
from tools.gimo_server.mcp_bridge.manifest import MANIFEST
from tools.gimo_server.mcp_bridge.bridge import proxy_to_api

logger = logging.getLogger("mcp_bridge.registrar")

def _safe_name(name: str) -> str:
    safe = name.replace("-", "_")
    if keyword.iskeyword(safe):
        safe = safe + "_"
    return safe

def register_all(mcp: FastMCP):
    count = 0
    for t_def in MANIFEST:
        try:
            name = t_def["name"]
            desc = t_def["description"]
            
            args_def = []
            param_mapping = ""  # To rebuild original names inside the function
            
            # Separate required and optional parameters to build a valid python signature
            required_params = []
            optional_params = []
            
            for p in t_def["params"]:
                p_type = p.get("type", "string")
                py_type = "str"
                if p_type == "integer": py_type = "int"
                elif p_type == "boolean": py_type = "bool"
                elif p_type == "number": py_type = "float"
                elif p_type == "array": py_type = "list"
                elif p_type == "object": py_type = "dict"
                
                req = p.get("required", False)
                orig_name = p["name"]
                safe_var = _safe_name(orig_name)
                
                param_mapping += f"    if {safe_var} is not None: __local_args['{orig_name}'] = {safe_var}\n"
                
                if req:
                    required_params.append(f"{safe_var}: {py_type}")
                else:
                    optional_params.append(f"{safe_var}: {py_type} | None = None")
            
            args_def = required_params + optional_params
            signature_str = ", ".join(args_def)
            
            # We generate a wrapper function via exec to get the exact signature for FastMCP
            func_code = f"""
async def {name}({signature_str}) -> str:
    \"\"\"{desc}\"\"\"
    __local_args = {{}}
{param_mapping}
    # Categorize params into path, query, and body
    path_args = {{}}
    query_args = {{}}
    body_args = {{}}
    
    for p_info in __tool_def['params']:
        orig = p_info['name']
        if orig in __local_args:
            loc = p_info.get('in', 'query')
            if loc == 'path':
                path_args[orig] = __local_args[orig]
            elif loc == 'query':
                query_args[orig] = __local_args[orig]
            else:
                body_args[orig] = __local_args[orig]
                
    kwargs = {{
        "__path_params": path_args,
        "__query": query_args,
        "__body": body_args if body_args else None
    }}
    
    return await proxy_to_api(__tool_def['method'], __tool_def['path'], **kwargs)
"""
            # Execute in a restricted scope with the required imports
            local_scope = {
                "proxy_to_api": proxy_to_api,
                "__tool_def": t_def
            }
            exec(func_code, local_scope)  # nosec B102 — generated from trusted OpenAPI spec, not user input
            
            # The function is now in local_scope[name]
            generated_func = local_scope[name]
            
            mcp.add_tool(generated_func)
            count += 1
            
        except Exception as e:
            logger.error(f"Failed to register tool {t_def.get('name')}: {e}")

    async def plan_create(
        objective: str,
        acceptance_criteria: list,
        intent_class: str,
        prompt: str | None = None,
    ) -> str:
        """Create a structured execution draft from objective + acceptance criteria."""
        body = {
            "objective": objective,
            "acceptance_criteria": acceptance_criteria,
            "execution": {"intent_class": intent_class},
        }
        if prompt is not None:
            body["prompt"] = prompt
        return await proxy_to_api("POST", "/ops/drafts", __body=body)

    async def plan_execute(draft_id: str, auto_run: bool = True) -> str:
        """Approve a draft and optionally trigger auto-run."""
        return await proxy_to_api(
            "POST",
            "/ops/drafts/{draft_id}/approve",
            __path_params={"draft_id": draft_id},
            __query={"auto_run": auto_run},
        )

    async def cost_estimate(nodes: list | None = None, initial_state: dict | None = None) -> str:
        """Estimate workflow cost using the mastery predictor endpoint."""
        return await proxy_to_api(
            "POST",
            "/ops/mastery/predict",
            __body={
                "nodes": nodes or [],
                "initial_state": initial_state or {},
            },
        )

    for alias in (plan_create, plan_execute, cost_estimate):
        try:
            mcp.add_tool(alias)
            count += 1
        except Exception as e:
            logger.error(f"Failed to register MCP alias {alias.__name__}: {e}")

    logger.info(f"Successfully registered {count} dynamic tools from manifest.")
