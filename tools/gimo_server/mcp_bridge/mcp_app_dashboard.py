"""MCP App Dashboard: Interactive governance UI within chat.

Registers a tool and resource that serve an interactive HTML dashboard
following the MCP Apps spec (ui:// resource scheme, sandboxed iframe,
bidirectional JSON-RPC via postMessage).
"""
import json
import logging
import os
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("mcp_bridge.dashboard")

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "dashboard_template.html")


def register_dashboard_app(mcp: FastMCP):

    @mcp.tool()
    async def gimo_dashboard() -> str:
        """Open the GIMO governance dashboard as interactive UI.

        Returns a reference to the dashboard that MCP Apps-capable clients
        (Claude App, VS Code) can render as an interactive iframe.
        """
        try:
            # Build a snapshot to embed as initial state
            from tools.gimo_server.models.surface import SurfaceIdentity
            from tools.gimo_server.services.sagp_gateway import SagpGateway

            surface = SurfaceIdentity(
                surface_type="claude_app",
                surface_name="gimo-dashboard",
            )
            snapshot = SagpGateway.get_snapshot(surface=surface)
            snapshot_json = json.dumps(snapshot.to_dict(), indent=2)

            return (
                f"GIMO Governance Dashboard\n"
                f"========================\n\n"
                f"Governance Snapshot:\n{snapshot_json}\n\n"
                f"To interact with governance:\n"
                f"- gimo_evaluate_action: Check if an action is allowed\n"
                f"- gimo_get_trust_profile: View trust scores\n"
                f"- gimo_get_budget_status: Check budget\n"
                f"- gimo_get_gics_insight: View GICS telemetry\n"
                f"- gimo_verify_proof_chain: Verify execution proofs"
            )
        except Exception as e:
            logger.error("gimo_dashboard failed: %s", e)
            return f"Dashboard error: {e}"

    @mcp.resource("ui://gimo-dashboard")
    async def dashboard_ui() -> str:
        """GIMO Governance Dashboard — Interactive HTML UI"""
        try:
            if os.path.exists(_TEMPLATE_PATH):
                with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
                    return f.read()
            else:
                return _fallback_dashboard_html()
        except Exception as e:
            logger.error("Failed to load dashboard template: %s", e)
            return _fallback_dashboard_html()

    logger.info("Registered MCP App Dashboard")


def _fallback_dashboard_html() -> str:
    """Minimal fallback if template file is missing."""
    return """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>GIMO Dashboard</title>
<style>body{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:20px}
h1{color:#58a6ff}code{background:#161b22;padding:2px 6px;border-radius:4px}</style>
</head><body>
<h1>GIMO Governance Dashboard</h1>
<p>Use governance tools for interaction:</p>
<ul>
<li><code>gimo_evaluate_action</code> - Check action governance</li>
<li><code>gimo_get_governance_snapshot</code> - Full state</li>
<li><code>gimo_get_trust_profile</code> - Trust scores</li>
<li><code>gimo_get_budget_status</code> - Budget forecast</li>
</ul>
</body></html>"""
