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
        return await _fetch_resource("/ui/audit?limit=50")

    logger.info("Registered 8 MCP Resources")
