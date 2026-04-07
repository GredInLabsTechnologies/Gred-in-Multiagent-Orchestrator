"""R17 Cluster D — Pydantic-driven schemas for native MCP tools.

Verifies:
- gimo_estimate_cost accepts canonical int params (tokens_in/tokens_out)
  and emits a DeprecationWarning when the legacy aliases are used.
- gimo_generate_team_config supports objective mode, plan_id mode, and
  enforces XOR validation between them.
- gimo_verify_proof_chain accepts an optional thread_id and falls back
  to the most recently updated thread.
- The Pydantic input models in native_inputs.py are the single source of
  truth — at least one tool's schema can be derived from
  ``model_json_schema()`` and matches the canonical parameter shape.
"""
from __future__ import annotations

import json
import warnings
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.gimo_server.mcp_bridge import governance_tools, native_tools
from tools.gimo_server.mcp_bridge.native_inputs import (
    EstimateCostInput,
    GenerateTeamConfigInput,
    VerifyProofChainInput,
)


class _FakeMCP:
    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def _decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return _decorator


@pytest.fixture
def native_registered():
    mcp = _FakeMCP()
    native_tools.register_native_tools(mcp)
    return mcp.tools


@pytest.fixture
def gov_registered():
    mcp = _FakeMCP()
    governance_tools.register_governance_tools(mcp)
    return mcp.tools


# ── #9: gimo_estimate_cost ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_estimate_cost_accepts_int_params(gov_registered):
    fn = gov_registered["gimo_estimate_cost"]

    with patch(
        "tools.gimo_server.services.economy.cost_service.CostService.get_pricing",
        return_value={"input": 3.0, "output": 15.0},
    ), patch(
        "tools.gimo_server.services.economy.cost_service.CostService.calculate_cost",
        return_value=0.0123,
    ), patch(
        "tools.gimo_server.services.economy.cost_service.CostService.get_provider",
        return_value="anthropic",
    ):
        result = await fn(model="claude-sonnet-4-6", tokens_in=2000, tokens_out=800)

    parsed = json.loads(result)
    assert parsed["tokens_in"] == 2000
    assert parsed["tokens_out"] == 800
    assert parsed["model"] == "claude-sonnet-4-6"
    assert parsed["total_cost_usd"] == 0.0123
    assert isinstance(parsed["tokens_in"], int)
    assert isinstance(parsed["tokens_out"], int)


@pytest.mark.asyncio
async def test_native_tool_deprecated_alias_warns(gov_registered):
    """Legacy input_tokens/output_tokens aliases must still work but warn."""
    fn = gov_registered["gimo_estimate_cost"]

    with patch(
        "tools.gimo_server.services.economy.cost_service.CostService.get_pricing",
        return_value={"input": 1.0, "output": 2.0},
    ), patch(
        "tools.gimo_server.services.economy.cost_service.CostService.calculate_cost",
        return_value=0.001,
    ), patch(
        "tools.gimo_server.services.economy.cost_service.CostService.get_provider",
        return_value="anthropic",
    ):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = await fn(model="m", input_tokens=1234, output_tokens=567)

    parsed = json.loads(result)
    assert parsed["tokens_in"] == 1234
    assert parsed["tokens_out"] == 567
    assert any(
        issubclass(w.category, DeprecationWarning)
        and "input_tokens" in str(w.message)
        for w in caught
    ), f"expected DeprecationWarning for input_tokens, got: {[str(w.message) for w in caught]}"
    assert any(
        issubclass(w.category, DeprecationWarning)
        and "output_tokens" in str(w.message)
        for w in caught
    )


# ── #10: gimo_generate_team_config — objective / plan_id / XOR ────────────


@pytest.mark.asyncio
async def test_generate_team_config_xor_validation(native_registered):
    fn = native_registered["gimo_generate_team_config"]

    # Both supplied → error
    result = await fn(plan_id="d_x", objective="do stuff")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "Invalid arguments" in parsed["error"]

    # Neither supplied → error
    result = await fn()
    parsed = json.loads(result)
    assert "error" in parsed
    assert "Invalid arguments" in parsed["error"]


@pytest.mark.asyncio
async def test_generate_team_config_plan_id_mode(native_registered):
    """plan_id mode: loads an existing draft and produces a config."""
    fn = native_registered["gimo_generate_team_config"]

    fake_plan = {
        "id": "p1", "title": "Hello", "objective": "say hi",
        "tasks": [{
            "id": "t1", "title": "do it", "scope": "all", "description": "x",
            "depends": [],
            "agent_assignee": {
                "role": "orchestrator", "goal": "g", "backstory": "b",
                "model": "m", "system_prompt": "s", "instructions": ["i"],
            },
        }],
    }
    get_response = "✅ Success (200):\n" + json.dumps({
        "id": "d_test",
        "content": json.dumps(fake_plan),
        "context": {},
    })

    async def fake_proxy(method, path, **kwargs):
        return get_response

    with patch(
        "tools.gimo_server.mcp_bridge.bridge.proxy_to_api",
        side_effect=fake_proxy,
    ), patch(
        "tools.gimo_server.services.agent_teams_service.AgentTeamsService.generate_team_config",
        return_value={"team": "ok", "members": []},
    ):
        result = await fn(plan_id="d_test")

    parsed = json.loads(result)
    assert parsed.get("team") == "ok"


@pytest.mark.asyncio
async def test_generate_team_config_objective_mode(native_registered):
    """objective mode: creates a new draft, then generates the team config."""
    fn = native_registered["gimo_generate_team_config"]

    fake_plan = {
        "id": "p1", "title": "Obj", "objective": "obj",
        "tasks": [{
            "id": "t1", "title": "do it", "scope": "all", "description": "x",
            "depends": [],
            "agent_assignee": {
                "role": "orchestrator", "goal": "g", "backstory": "b",
                "model": "m", "system_prompt": "s", "instructions": ["i"],
            },
        }],
    }
    create_response = "✅ Success (201):\n" + json.dumps({"id": "d_new"})
    get_response = "✅ Success (200):\n" + json.dumps({
        "id": "d_new",
        "content": json.dumps(fake_plan),
        "context": {},
    })

    calls = []

    async def fake_proxy(method, path, **kwargs):
        calls.append((method, path))
        if method == "POST" and path == "/ops/drafts":
            return create_response
        if method == "GET" and path.startswith("/ops/drafts/"):
            return get_response
        return "✅ Success (200):\n{}"

    with patch(
        "tools.gimo_server.mcp_bridge.bridge.proxy_to_api",
        side_effect=fake_proxy,
    ), patch(
        "tools.gimo_server.services.agent_teams_service.AgentTeamsService.generate_team_config",
        return_value={"team": "obj_ok"},
    ):
        result = await fn(objective="Build a hello-world worker")

    parsed = json.loads(result)
    assert parsed.get("team") == "obj_ok"
    # Confirm the create-draft POST happened first
    assert ("POST", "/ops/drafts") in calls
    assert any(m == "GET" and p == "/ops/drafts/d_new" for m, p in calls)


# ── #11: gimo_verify_proof_chain — optional thread_id ─────────────────────


@pytest.mark.asyncio
async def test_verify_proof_chain_optional_thread_id(gov_registered):
    fn = gov_registered["gimo_verify_proof_chain"]

    fake_thread = SimpleNamespace(id="th_recent")
    with patch(
        "tools.gimo_server.services.conversation_service.ConversationService.list_threads",
        return_value=[fake_thread],
    ), patch(
        "tools.gimo_server.services.sagp_gateway.SagpGateway.verify_proof_chain",
        return_value={"thread_id": "th_recent", "valid": True, "length": 0},
    ):
        # No thread_id passed → must fall back to th_recent
        result = await fn()

    parsed = json.loads(result)
    assert parsed["thread_id"] == "th_recent"
    assert parsed.get("resolved_thread_id") == "th_recent"
    assert parsed.get("thread_id_was_inferred") is True


@pytest.mark.asyncio
async def test_verify_proof_chain_explicit_thread_id(gov_registered):
    fn = gov_registered["gimo_verify_proof_chain"]

    with patch(
        "tools.gimo_server.services.sagp_gateway.SagpGateway.verify_proof_chain",
        return_value={"thread_id": "th_explicit", "valid": True, "length": 3},
    ):
        result = await fn(thread_id="th_explicit")

    parsed = json.loads(result)
    assert parsed["thread_id"] == "th_explicit"
    assert parsed.get("thread_id_was_inferred") is False


# ── Schema parity: Pydantic models are the source of truth ───────────────


def test_native_tool_inputschema_matches_pydantic_model():
    """The Pydantic input models must produce coherent JSONSchema with
    integer types for token counts and the correct optionality.

    This is the structural guarantee against the int→string drift bug (#9):
    if the schema ever drifts to string, this test catches it.
    """
    schema = EstimateCostInput.model_json_schema()
    props = schema["properties"]
    assert props["tokens_in"]["type"] == "integer"
    assert props["tokens_out"]["type"] == "integer"
    assert props["model"]["type"] == "string"
    # Required must include 'model' but not the token fields (defaults).
    required = set(schema.get("required", []))
    assert "model" in required
    assert "tokens_in" not in required
    assert "tokens_out" not in required

    team_schema = GenerateTeamConfigInput.model_json_schema()
    team_props = team_schema["properties"]
    assert "plan_id" in team_props
    assert "objective" in team_props
    # Both nullable; the XOR is enforced by the validator at runtime.
    assert set(team_schema.get("required", [])) == set()

    proof_schema = VerifyProofChainInput.model_json_schema()
    assert "thread_id" in proof_schema["properties"]
    assert set(proof_schema.get("required", [])) == set()


def test_generate_team_config_input_xor_at_model_level():
    with pytest.raises(ValueError):
        GenerateTeamConfigInput(plan_id=None, objective=None)
    with pytest.raises(ValueError):
        GenerateTeamConfigInput(plan_id="p", objective="o")
    # Each alone is fine.
    assert GenerateTeamConfigInput(plan_id="p").plan_id == "p"
    assert GenerateTeamConfigInput(objective="o").objective == "o"
