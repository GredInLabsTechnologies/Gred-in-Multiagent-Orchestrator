import sys
import pprint
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.gimo_server.main import app

def generate_manifest():
    openapi = app.openapi()
    tools = []
    
    for path, path_item in openapi.get("paths", {}).items():
        if not path.startswith("/ops/"):
            continue
            
        for method, operation in path_item.items():
            if method not in ["get", "post", "put", "delete", "patch"]:
                continue
                
            tool_name = operation.get("operationId", f"{method.upper()}_{path.replace('/', '_')}")
            tool_name = tool_name.replace("-", "_").replace("/", "_").strip("_")
            
            # fastmcp doesn't allow more than 64 char names, let's keep it safe
            if len(tool_name) > 63:
                tool_name = tool_name[:63]
            
            params = []
            for param in operation.get("parameters", []):
                schema = param.get("schema", {})
                # Resolve anyOf (Optional[X] produces anyOf: [{type: X}, {type: null}])
                ptype = schema.get("type", "string")
                if ptype == "string" and "anyOf" in schema:
                    for variant in schema["anyOf"]:
                        if isinstance(variant, dict) and variant.get("type") != "null":
                            ptype = variant.get("type", "string")
                            break
                params.append({
                    "name": param["name"],
                    "type": ptype,
                    "required": param.get("required", False),
                    "in": param.get("in", "query")
                })
            
            req_body = operation.get("requestBody", {})
            if req_body:
                content = req_body.get("content", {}).get("application/json", {})
                schema = content.get("schema", {})
                
                # Resolve $ref if present
                if "$ref" in schema:
                    ref_name = schema["$ref"].split("/")[-1]
                    ref_schema = openapi.get("components", {}).get("schemas", {}).get(ref_name, {})
                    for prop_name, prop_val in ref_schema.get("properties", {}).items():
                        params.append({
                            "name": prop_name,
                            "type": prop_val.get("type", "string") if isinstance(prop_val, dict) else "string",
                            "required": prop_name in ref_schema.get("required", []),
                            "in": "body"
                        })
                # If there are direct properties in the schema
                elif "properties" in schema:
                    for prop_name, prop_val in schema.get("properties", {}).items():
                        params.append({
                            "name": prop_name,
                            "type": prop_val.get("type", "string") if isinstance(prop_val, dict) else "string",
                            "required": prop_name in schema.get("required", []),
                            "in": "body"
                        })
            
            tools.append({
                "name": tool_name.lower(),
                "method": method.upper(),
                "path": path,
                "description": operation.get("summary", f"Endpoint {method.upper()} {path}"),
                "params": params
            })
            
    out_dir = Path("tools/gimo_server/mcp_bridge")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "manifest.py"
    
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("# AUTO-GENERATED FILE. DO NOT EDIT.\n")
        f.write("MANIFEST = ")
        f.write(pprint.pformat(tools, indent=4))
        f.write("\n")
        
    print(f"Generated {len(tools)} tools in {out_file}")

if __name__ == "__main__":
    generate_manifest()
