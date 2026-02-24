import pytest
import os
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[1]))

# Delayed import key to avoiding config load before setup?
# Actually we can patch the config.TOKENS after import.

from tools.gimo_server.config import OPS_DATA_DIR
# Ensure we write tokens BEFORE importing modules that might cache them if we could, 
# but here we can just update the list.

from tools.gimo_server import config
from tools.gimo_server.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

def setup_module(module):
    # Ensure tokens exist with known values
    (OPS_DATA_DIR / ".orch_token").write_text("orch_token", encoding="utf-8")
    (OPS_DATA_DIR / ".orch_actions_token").write_text("orch_actions_token", encoding="utf-8")
    (OPS_DATA_DIR / ".orch_operator_token").write_text("orch_operator_token", encoding="utf-8")
    (OPS_DATA_DIR / ".orch_admin_token").write_text("orch_admin_token", encoding="utf-8")
    
    # Reload or patch config tokens
    # config.py does: TOKENS = {ORCH_TOKEN, ORCH_ACTIONS_TOKEN, ORCH_OPERATOR_TOKEN}
    # We need to update these values in the `config` module if they were read from file at import time.
    
    # Let's see how config.py reads them. 
    # If it reads them at module level:
    # ORCH_TOKEN = (OPS_DATA_DIR / ".orch_token").read_text().strip()
    
    # We can manually patch them to be safe
    config.ORCH_TOKEN = "orch_token"
    # config.ORCH_ACTIONS_TOKEN = "orch_actions_token" # Might be read from env or file
    # config.ORCH_OPERATOR_TOKEN = "orch_operator_token"
    
    # Patch auth module directly 
    from tools.gimo_server.security import auth
    known_tokens = {"orch_token_long_enough_for_validation", "orch_actions_token_long_enough", "orch_operator_token_long_enough", "orch_admin_token_long_enough"}
    config.TOKENS = known_tokens
    auth.TOKENS = known_tokens
    auth.ORCH_TOKEN = "orch_token_long_enough_for_validation"
    auth.ORCH_ACTIONS_TOKEN = "orch_actions_token_long_enough"
    auth.ORCH_OPERATOR_TOKEN = "orch_operator_token_long_enough"

def test_mcp_flow():
    # Use the token we know is in TOKENS and has admin rights (orch_token typically)
    # Ensure no trailing whitespace issues etc
    token = "orch_token_long_enough_for_validation"
    auth_headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Configure MCP Server

    # 1. Configure MCP Server
    # We point to our dummy server script
    dummy_script = Path(__file__).parent / "dummy_mcp_server.py"
    command = sys.executable
    args = [str(dummy_script)]
    
    
    # First get current config
    
    # First get current config
    resp = client.get("/ops/provider", headers=auth_headers)
    assert resp.status_code == 200, f"Failed to get provider config: {resp.text}"
    existing_config = resp.json()
    existing_config = resp.json()
    
    # Add dummy mcp server
    mcp_config = {
        "dummy": {
            "command": command,
            "args": args,
            "env": {},
            "enabled": True
        }
    }
    
    existing_config["mcp_servers"] = mcp_config
    
    resp = client.put("/ops/provider", json=existing_config, headers=auth_headers)
    assert resp.status_code == 200, f"Failed to update provider config: {resp.text}"
    
    # 2. Verify it appears in /config/mcp
    resp = client.get("/ops/config/mcp", headers=auth_headers)
    assert resp.status_code == 200
    servers = resp.json()["servers"]
    assert any(s["name"] == "dummy" for s in servers)
    
    # 3. Trigger Sync
    # Post to sync
    resp = client.post("/ops/config/mcp/sync", json={"server_name": "dummy"}, headers=auth_headers)
    assert resp.status_code == 200, f"Sync failed: {resp.text}"
    data = resp.json()
    assert "dummy" == data["server"]
    # We expect at least the tools from dummy_mcp_server.py
    # They should be prefixed with "dummy_"
    print(f"Discovered tools: {data.get('tools')}")
    assert "dummy_echo" in data["tools"]
    
    # 4. Verify in Tool Registry
    resp = client.get("/ops/tool-registry/dummy_echo", headers=auth_headers)
    assert resp.status_code == 200
    tool_data = resp.json()
    assert tool_data["name"] == "dummy_echo"
    assert tool_data["description"] == "Echoes back the input"
    
    print("MCP Flow Verification Passed!")

if __name__ == "__main__":
    try:
        setup_module(None)
        test_mcp_flow()
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)
