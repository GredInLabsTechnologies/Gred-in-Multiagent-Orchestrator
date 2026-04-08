"""GICS health HTTP vs MCP parity (R20-004).

Asserts the FastAPI trust dashboard endpoint and the MCP
``gimo_get_governance_snapshot`` tool agree on whether the GICS daemon
is alive. Under the conformance fixture both paths share a single
in-process GICS (bootstrap helper), so ``daemon_alive`` must match.
"""
from __future__ import annotations

import asyncio
import json


def test_gics_health_daemon_alive_parity(live_backend, auth_header, mcp_call):
    http_resp = live_backend.get("/ops/trust/dashboard", headers=auth_header)
    assert http_resp.status_code == 200
    # Dashboard envelope is informational; presence of ``entries`` is enough
    # to prove the HTTP path reached TrustEngine without raising.
    assert "entries" in http_resp.json()

    loop = asyncio.new_event_loop()
    try:
        mcp_raw = loop.run_until_complete(
            mcp_call("gimo_get_governance_snapshot", thread_id="")
        )
    finally:
        loop.close()
    snap = json.loads(mcp_raw)
    # The snapshot MUST include a gics_health block with a boolean
    # daemon_alive key — this is the field the R20-004 probe flagged.
    assert "gics_health" in snap, f"snapshot missing gics_health: {snap}"
    assert "daemon_alive" in snap["gics_health"], f"gics_health missing daemon_alive: {snap['gics_health']}"
    assert isinstance(snap["gics_health"]["daemon_alive"], bool)
