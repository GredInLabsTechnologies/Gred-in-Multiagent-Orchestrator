"""OperatorClass HTTP vs MCP parity (R20-001).

The MCP surface MUST mark drafts ``cognitive_agent`` so policy gating
whitelists them at the fallback-to-human branch. The UI/HTTP surface
without an explicit ``operator_class`` MUST default to ``human_ui`` so
human approval remains enforced.

We assert at the draft-creation level (the root of R20-001) rather
than forcing an end-to-end run, because the conformance layer must
not require a real LLM backend.
"""
from __future__ import annotations


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


def test_mcp_context_draft_is_cognitive_agent(live_backend, auth_header):
    body = {
        "objective": "Investigate MCP-path operator_class propagation",
        "acceptance_criteria": ["context.operator_class=cognitive_agent must persist"],
        "execution": {"intent_class": "DOC_UPDATE"},
        "context": {"operator_class": "cognitive_agent"},
    }
    # The MCP bridge today passes operator_class via the draft context
    # (see tools/gimo_server/mcp_bridge/native_tools.py::gimo_create_draft
    # and tools/gimo_server/services/agent_broker_service.py).
    headers = {**auth_header, "X-Gimo-Surface": "mcp"}
    resp = live_backend.post("/ops/drafts", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    draft = resp.json()
    assert draft.get("operator_class") == "cognitive_agent"
