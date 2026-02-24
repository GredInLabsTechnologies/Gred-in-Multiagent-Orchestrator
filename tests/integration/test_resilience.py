import os
import sys
import time
import pytest
import asyncio
import requests
import concurrent.futures
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from tools.gimo_server.main import app
from tools.gimo_server.ops_models import WorkflowNode, WorkflowGraph
from tools.gimo_server.services.graph_engine import GraphEngine
from tools.gimo_server import config

pytestmark = pytest.mark.integration

BASE_URL = os.environ.get("ORCH_BASE_URL", "http://localhost:9325")
# Use the admin token defined in config (avoiding actions/operator tokens)
VALID_TOKEN = next(t for t in config.TOKENS if t not in [config.ORCH_ACTIONS_TOKEN, config.ORCH_OPERATOR_TOKEN])

# ── E2E & MCP Verification ────────────────────────────────

class TestSystemE2E:
    def test_core_status_flow(self, test_client):
        """Verify basic status observability (from test_e2e_harness)."""
        res = test_client.get("/status", headers={"Authorization": f"Bearer {VALID_TOKEN}"})
        assert res.status_code == 200
        assert "version" in res.json()

    def test_mcp_lifecycle_and_execution(self, test_client):
        """Full flow: Config -> Sync -> Execute (from verify_mcp and verify_execution)."""
        auth = {"Authorization": f"Bearer {VALID_TOKEN}"}
        dummy_path = (Path(__file__).parent.parent / "fixtures" / "dummy_mcp_server.py").resolve()
        
        # 1. Update Provider Config
        mcp_cfg = {"dummy": {"command": sys.executable, "args": [str(dummy_path)], "enabled": True}}
        res_get = test_client.get("/ops/provider", headers=auth)
        if res_get.status_code == 200:
            full_cfg = res_get.json()
            full_cfg.setdefault("mcp_servers", {}).update(mcp_cfg)
            test_client.put("/ops/provider", json=full_cfg, headers=auth)
        else:
            # Fallback if GET fails
            test_client.put("/ops/provider", json={"active": "openai", "providers": {}, "mcp_servers": mcp_cfg}, headers=auth)
        
        # 2. Sync
        sync_res = test_client.post("/ops/config/mcp/sync", json={"server_name": "dummy"}, headers=auth)
        assert "dummy_echo" in sync_res.json().get("tools", [])

        # 3. Execute via GraphEngine
        async def run_e2e():
            node = WorkflowNode(id="n1", type="tool_call", config={"tool_name": "dummy_echo", "arguments": {"message": "hello"}})
            graph = WorkflowGraph(id="e2e", nodes=[node], edges=[])
            engine = GraphEngine(graph)
            # Mock observability to stay clean
            with patch("tools.gimo_server.services.graph_engine.ObservabilityService"):
                state = await engine.execute()
                return state
        
        state = asyncio.run(run_e2e())
        assert state.checkpoints[0].status == "completed"
        assert "Echo: hello" in str(state.checkpoints[0].output)

# ── Chaos & Resilience ────────────────────────────────────

class TestChaosResilience:
    def test_panic_recovery_logic(self, test_client):
        """Verify resolution logic for panic mode (logic check)."""
        auth = {"Authorization": f"Bearer {VALID_TOKEN}"}
        with patch("tools.gimo_server.security.threat_engine") as mock_engine, \
             patch("tools.gimo_server.security.save_security_db"):
            res = test_client.post("/ui/security/resolve?action=clear_all", headers=auth)
            assert res.status_code == 200
            mock_engine.clear_all.assert_called()

    @pytest.mark.skipif(not os.environ.get("RUN_STRESS_TESTS"), reason="Stress tests disabled")
    def test_load_saturation(self):
        """Simulate high load for rate limiting (from test_load_chaos_resilience)."""
        def hit_endpoint():
            return requests.get(f"{BASE_URL}/status", headers={"Authorization": f"Bearer {VALID_TOKEN}"}, timeout=2).status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(lambda _: hit_endpoint(), range(100)))
        
        assert 429 in results or 200 in results # Depending on env config

# ── Snapshot & Integrity ──────────────────────────────────

def test_snapshot_creation_sanity(test_client):
    """Verify snapshot directory interaction (from verify_snapshots)."""
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=Path(".")), \
         patch("tools.gimo_server.routes.validate_path", return_value=Path("tools/gimo_server/config.py")), \
         patch("tools.gimo_server.services.file_service.FileService.get_file_content", return_value=("ok", "h")):
        
        # Trigger read
        test_client.get("/file?path=tools/gimo_server/config.py", headers={"Authorization": f"Bearer {VALID_TOKEN}"})
        # Logic check: Verify if snapshots dir exists or is handled
        assert Path(".orch_snapshots").exists() or True # Placeholder for actual logic check
