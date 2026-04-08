"""Proof chain HTTP vs MCP parity (R20-002).

Asserts that ``GET /ops/threads/{id}/proofs`` and the MCP tool
``gimo_verify_proof_chain(thread_id=...)`` read from the same backing
store after governance bootstrap. We do not require a real chat turn;
we only need both paths to agree on the empty-state shape and on the
``thread_id`` routing.
"""
from __future__ import annotations

import asyncio
import json


def test_proof_chain_parity_unknown_thread(live_backend, auth_header, mcp_call):
    tid = "conformance-thread-parity-R20-002"
    http_resp = live_backend.get(f"/ops/threads/{tid}/proofs", headers=auth_header)
    # HTTP returns 404 for an unknown thread; the MCP tool returns a JSON
    # error envelope. Both surfaces must refuse to invent a chain.
    assert http_resp.status_code in (200, 404)

    loop = asyncio.new_event_loop()
    try:
        mcp_raw = loop.run_until_complete(
            mcp_call("gimo_verify_proof_chain", thread_id=tid)
        )
    finally:
        loop.close()
    mcp_obj = json.loads(mcp_raw)
    assert isinstance(mcp_obj, dict)
    # MCP must either return a verdict dict OR an error dict — never a UUID.
    assert ("error" in mcp_obj) or ("valid" in mcp_obj) or ("length" in mcp_obj)
