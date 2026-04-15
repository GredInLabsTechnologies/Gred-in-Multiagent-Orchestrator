import json
import logging
import httpx
from mcp.server.fastmcp import FastMCP
from .bridge import _get_auth_token, BACKEND_URL

logger = logging.getLogger("mcp_bridge.resources")


async def _fetch_resource(path: str) -> str:
    try:
        headers = {}
        token = _get_auth_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BACKEND_URL}{path}", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return json.dumps(data, indent=2)
            else:
                return f"Error: HTTP {resp.status_code} - {resp.text}"
    except Exception as e:
        return f"Error fetching {path}: {e}"

def register_resources(mcp: FastMCP):
    @mcp.resource("config://app")
    async def get_app_config() -> str:
        """Global GIMO Application Configuration"""
        return await _fetch_resource("/ops/config")

    @mcp.resource("runs://recent")
    async def get_recent_runs() -> str:
        """List of 20 most recent GIMO Ops Runs"""
        return await _fetch_resource("/ops/runs?limit=20")

    @mcp.resource("drafts://recent")
    async def get_recent_drafts() -> str:
        """List of 20 most recent unapproved plan Drafts"""
        return await _fetch_resource("/ops/drafts?limit=20")

    @mcp.resource("metrics://roi")
    async def get_roi_metrics() -> str:
        """Return on Investment (ROI) metrics for sub-agents"""
        return await _fetch_resource("/ops/mastery/analytics")

    @mcp.resource("metrics://cascade")
    async def get_cascade_metrics() -> str:
        """Model delegation cascade statistics"""
        return await _fetch_resource("/ops/mastery/status")

    @mcp.resource("metrics://cache")
    async def get_cache_metrics() -> str:
        """Semantic Cache hit/miss metrics"""
        return await _fetch_resource("/ops/observability/metrics")

    @mcp.resource("security://trust")
    async def get_trust_dashboard() -> str:
        """Agent Trust and Circuit Breaker statuses"""
        return await _fetch_resource("/ops/trust/dashboard")

    @mcp.resource("audit://log")
    async def get_audit_log() -> str:
        """Recent security audit logs"""
        return await _fetch_resource("/ops/audit/tail?limit=50")

    # ── SAGP Governance Resources ───────────────────────────────────────
    @mcp.resource("governance://snapshot")
    async def get_governance_snapshot() -> str:
        """Complete SAGP governance snapshot: policy, trust, budget, GICS, proofs"""
        try:
            from tools.gimo_server.models.surface import SurfaceIdentity
            from tools.gimo_server.services.sagp_gateway import SagpGateway
            surface = SurfaceIdentity(surface_type="mcp_generic", surface_name="mcp-resource")
            snapshot = SagpGateway.get_snapshot(surface=surface)
            return json.dumps(snapshot.to_dict(), indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.resource("governance://policies")
    async def get_governance_policies() -> str:
        """All available execution policies and their configurations"""
        try:
            from tools.gimo_server.services.execution.execution_policy_service import EXECUTION_POLICIES
            policies = {}
            for name, p in EXECUTION_POLICIES.items():
                policies[name] = {
                    "fs_mode": p.fs_mode,
                    "network_mode": p.network_mode,
                    "max_cost_per_turn_usd": p.max_cost_per_turn_usd,
                    "hitl_required": p.hitl_required,
                    "allowed_tools_count": len(p.allowed_tools),
                }
            return json.dumps(policies, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.resource("gics://health")
    async def get_gics_health() -> str:
        """GICS daemon health summary: alive status, entry count"""
        try:
            from tools.gimo_server.services.gics_service import GicsService
            gics = GicsService()
            alive = hasattr(gics, "_daemon") and gics._daemon is not None
            count = gics.count_prefix("") if hasattr(gics, "count_prefix") else 0
            return json.dumps({"daemon_alive": alive, "entry_count": count}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    logger.info("Registered 11 MCP Resources")
