"""OperatorClass HTTP vs MCP parity (R20-001 / R21).

The MCP surface MUST mark drafts ``cognitive_agent`` so policy gating
whitelists them at the fallback-to-human branch. The UI/HTTP surface
without an explicit ``operator_class`` MUST default to ``human_ui`` so
human approval remains enforced.

R21 fix: enter the MCP path through the actual ``gimo_create_draft``
bridge wrapper (not by hand-crafting the HTTP body) so any future
regression where the wrapper drops ``context.operator_class`` is caught.
"""
from __future__ import annotations

import asyncio
import json
import re

import httpx
import pytest


def test_http_default_draft_is_human_ui(live_backend, auth_header):
    body = {
        "objective": "Investigate conformance default operator_class",
        "acceptance_criteria": ["default must be human_ui"],
        "execution": {"intent_class": "DOC_UPDATE"},
    }
    resp = live_backend.post("/ops/drafts", json=body, headers=auth_header)
    assert resp.status_code == 201, resp.text
    draft = resp.json()
    assert draft.get("operator_class") == "human_ui"


def test_mcp_context_draft_is_cognitive_agent(live_backend, auth_header, monkeypatch):
    """Enter through the real gimo_create_draft MCP bridge wrapper.

    The wrapper calls ``bridge.proxy_to_api`` which normally hits
    127.0.0.1:9325 over HTTP. We monkeypatch ``httpx.AsyncClient`` so
    the request is dispatched against the in-process FastAPI
    ``live_backend`` TestClient instead. This proves the wrapper itself
    injects ``context.operator_class=cognitive_agent``.
    """
    from mcp.server.fastmcp import FastMCP
    from tools.gimo_server.mcp_bridge.native_tools import register_native_tools
    from tools.gimo_server.mcp_bridge import bridge as bridge_mod

    class _StubResponse:
        def __init__(self, resp):
            self.status_code = resp.status_code
            self.text = resp.text
            self._json = None
            try:
                self._json = resp.json()
            except Exception:
                pass

        def json(self):
            if self._json is None:
                raise ValueError("no json")
            return self._json

    class _StubClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def build_request(self, method, url, params=None, json=None, headers=None):
            path = re.sub(r"^https?://[^/]+", "", url)
            return ("REQ", method, path, params or {}, json, headers or {})

        async def send(self, request):
            _, method, path, params, body, headers = request
            tc_headers = {**auth_header, **headers}
            if method.upper() == "POST":
                resp = live_backend.post(path, params=params, json=body, headers=tc_headers)
            else:
                resp = live_backend.get(path, params=params, headers=tc_headers)
            return _StubResponse(resp)

    monkeypatch.setattr(bridge_mod.httpx, "AsyncClient", _StubClient)

    mcp = FastMCP("gimo-conformance-native")
    register_native_tools(mcp)
    manager = getattr(mcp, "_tool_manager", None) or getattr(mcp, "tool_manager", None)
    tools = getattr(manager, "_tools", None) or getattr(manager, "tools", None) or {}
    tool = tools.get("gimo_create_draft")
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None) or tool

    result = asyncio.get_event_loop().run_until_complete(
        fn(task_instructions="R21 conformance: MCP draft must be cognitive_agent")
    )
    assert "Success (201)" in result, result
    payload = json.loads(result.split("\n", 1)[1])
    assert payload.get("operator_class") == "cognitive_agent", payload
