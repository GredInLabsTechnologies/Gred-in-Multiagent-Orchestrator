
import pytest
import asyncio
import sys
import json
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[1]))

from tools.gimo_server.config import OPS_DATA_DIR
from tools.gimo_server import config
from tools.gimo_server.main import app
from fastapi.testclient import TestClient

from tools.gimo_server.ops_models import WorkflowNode, WorkflowGraph
from tools.gimo_server.services.graph_engine import GraphEngine

client = TestClient(app)

def setup_module(module):
    # Ensure tokens exist with known values (reusing logic from verify_mcp.py)
    # Patch auth module directly 
    from tools.gimo_server.security import auth
    known_tokens = {"orch_token_long_enough_for_validation", "orch_actions_token_long_enough", "orch_operator_token_long_enough", "orch_admin_token_long_enough"}
    config.TOKENS = known_tokens
    auth.TOKENS = known_tokens
    auth.ORCH_TOKEN = "orch_token_long_enough_for_validation"
    
def test_e2e_execution():
    print("\n--- Starting E2E Execution Test ---")
    token = "orch_token_long_enough_for_validation"
    auth_headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Configure MCP Server (Dummy)
    dummy_script = Path(__file__).parent / "dummy_mcp_server.py"
    command = sys.executable
    args = [str(dummy_script)]
    
    # Get current config
    resp = client.get("/ops/provider", headers=auth_headers)
    assert resp.status_code == 200
    existing_config = resp.json()
    
    # Update with dummy server
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
    assert resp.status_code == 200
    
    # 2. Sync Tools
    resp = client.post("/ops/config/mcp/sync", json={"server_name": "dummy"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "dummy_echo" in data["tools"]
    print("Tools synced successfully.")
    
    # 3. Create Graph with Tool Call
    # Note: Tool name in registry is "dummy_echo" (prefixed)
    node = WorkflowNode(
        id="node_1",
        type="tool_call",
        config={
            "tool_name": "dummy_echo",
            "arguments": {"message": "E2E_TEST_SUCCESS"}
        }
    )
    graph = WorkflowGraph(id="e2e_graph", nodes=[node], edges=[])
    
    # 4. Execute using GraphEngine directly
    # GraphEngine uses ToolRegistryService which reads from disk
    # Since we synced via API, the registry file on disk should be updated
    
    # Patch Observability to avoid console spam
    from unittest.mock import patch
    
    async def run_engine():
        with patch("tools.gimo_server.services.graph_engine.ObservabilityService") as MockObs:
            # Mock the trace context manager
            MockObs.start_as_current_span.return_value.__enter__.return_value = None
            MockObs.start_as_current_span.return_value.__exit__.return_value = None
            
            engine = GraphEngine(graph)
            print("Executing graph...")
            state = await engine.execute()
            return state
        
    state = asyncio.run(run_engine())
    
    # 5. Verify Output
    # Checkpoints should contain the result
    assert len(state.checkpoints) == 1
    chk = state.checkpoints[0]
    assert chk.node_id == "node_1"
    assert chk.status == "completed"
    
    output = chk.output
    # Output format from _execute_node:
    # {
    #     "tool": tool_name,
    #     "input": args,
    #     "output": result,
    #     "mcp_server": mcp_server
    # }
    print(f"Node Output: {output}")
    
    # Check that the tool actually ran and returned the echo
    # dummy_echo returns string "Echo: {message}"
    assert output["tool"] == "dummy_echo"
    assert output["mcp_server"] == "dummy"
    # Result from McpClient.call_tool is the raw result from server
    # Structure: {'content': [{'type': 'text', 'text': 'Echo: ...'}]}
    tool_result = output["output"]
    assert "content" in tool_result
    item = tool_result["content"][0]
    assert item["type"] == "text"
    assert item["text"] == "Echo: E2E_TEST_SUCCESS"
    
    print("E2E Execution Verified Successfully!")

if __name__ == "__main__":
    setup_module(None)
    test_e2e_execution()
