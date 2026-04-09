"""R17.1 follow-up tests — close the three regressions surfaced by the
peer review of R17:

1. Cluster D: real FastMCP introspection of the published tool schema
   (not just ``Model.model_json_schema()`` of the helper).
2. Cluster D: ``gimo_generate_team_config`` objective mode MUST delegate
   to ``/ops/generate-plan`` (single backend authority) — see
   ``test_native_tools_r17_cluster_d::test_generate_team_config_objective_mode``.
3. Cluster E.2: ``ProviderDiagnosticsService._auth_probe`` MUST inspect
   the normalized ``ProviderEntry`` (auth_mode + provider_type), not the
   raw provider_id, so account-mode IDs like ``codex-main`` are routed
   correctly.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tools.gimo_server.mcp_bridge import governance_tools, native_tools
from tools.gimo_server.models.provider import ProviderConfig, ProviderEntry
from tools.gimo_server.services.providers.provider_diagnostics_service import (
    ProviderDiagnosticsService,
)


# ───────────────────────────────────────────────────────────────────────
# (1) Real FastMCP introspection — schema is sourced from the live registry
# ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def live_mcp():
    """Register native + governance tools on a real FastMCP instance and
    return the instance so tests can introspect _tool_manager._tools."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("r17_1_test")
    governance_tools.register_governance_tools(mcp)
    native_tools.register_native_tools(mcp)
    return mcp


def _params_for(mcp, tool_name: str) -> dict:
    """Return the published JSONSchema parameters for a registered tool."""
    tool = mcp._tool_manager._tools[tool_name]
    # FastMCP exposes the input schema either as `parameters` (older) or
    # `inputSchema` / `input_schema` (newer). Try the common shapes.
    for attr in ("parameters", "inputSchema", "input_schema"):
        schema = getattr(tool, attr, None)
        if schema:
            return schema
    # Fall back to the underlying fn signature reflection if FastMCP exposes it
    if hasattr(tool, "fn_metadata"):
        meta = tool.fn_metadata
        for attr in ("arg_model", "schema", "parameters"):
            schema_obj = getattr(meta, attr, None)
            if schema_obj is not None:
                if hasattr(schema_obj, "model_json_schema"):
                    return schema_obj.model_json_schema()
                return schema_obj
    raise AssertionError(f"Cannot locate parameter schema for tool {tool_name}")


def test_estimate_cost_published_schema_has_no_alias_fields(live_mcp):
    """The MCP-published schema for gimo_estimate_cost MUST NOT carry the
    deprecated input_tokens/output_tokens fields after R17.1."""
    schema = _params_for(live_mcp, "gimo_estimate_cost")
    props = schema.get("properties", {})
    assert "tokens_in" in props
    assert "tokens_out" in props
    assert "input_tokens" not in props, (
        f"deprecated alias 'input_tokens' still in published schema: {props}"
    )
    assert "output_tokens" not in props, (
        f"deprecated alias 'output_tokens' still in published schema: {props}"
    )
    # Type integrity (#9 — int → string drift guard at the live-schema level)
    assert props["tokens_in"].get("type") == "integer"
    assert props["tokens_out"].get("type") == "integer"


def test_generate_team_config_published_schema_has_xor_fields(live_mcp):
    """The published schema must expose plan_id and objective as the only
    two non-hidden parameters; XOR is enforced at runtime by Pydantic."""
    schema = _params_for(live_mcp, "gimo_generate_team_config")
    props = schema.get("properties", {})
    assert "plan_id" in props
    assert "objective" in props
    # Neither field is required at the schema level — runtime XOR is the
    # contract; the docstring/description must mention this.
    required = set(schema.get("required", []) or [])
    assert "plan_id" not in required
    assert "objective" not in required


# ───────────────────────────────────────────────────────────────────────
# (2) Cluster E.2: account-mode probe with custom IDs
# ───────────────────────────────────────────────────────────────────────


def _config_with(provider_id: str, ptype: str, auth_mode: str) -> ProviderConfig:
    return ProviderConfig(
        active=provider_id,
        providers={
            provider_id: ProviderEntry(
                type=ptype,
                provider_type=ptype,
                auth_mode=auth_mode,
                model="x",
            )
        },
    )


@pytest.mark.asyncio
async def test_auth_probe_routes_codex_account_with_custom_id():
    """codex-main (custom account-mode ID) MUST be routed to CodexAuthService,
    not fall through to the API-key fallback and report 'missing'."""
    cfg = _config_with("codex-main", "codex", "account")
    with patch(
        "tools.gimo_server.services.providers.service.ProviderService.get_config",
        return_value=cfg,
    ), patch(
        "tools.gimo_server.services.codex_auth_service.CodexAuthService.get_auth_status",
        new=AsyncMock(return_value={"authenticated": True, "method": "cli"}),
    ) as codex_mock:
        status, method, error = await ProviderDiagnosticsService._auth_probe("codex-main")

    assert status == "ok"
    assert method == "cli"
    assert error is None
    codex_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_probe_routes_claude_account_with_custom_id():
    """claude-prod (custom claude account-mode ID) MUST hit ClaudeAuthService."""
    cfg = _config_with("claude-prod", "claude", "account")
    with patch(
        "tools.gimo_server.services.providers.service.ProviderService.get_config",
        return_value=cfg,
    ), patch(
        "tools.gimo_server.services.claude_auth_service.ClaudeAuthService.get_auth_status",
        new=AsyncMock(return_value={"authenticated": True, "method": "cli"}),
    ) as claude_mock:
        status, method, _ = await ProviderDiagnosticsService._auth_probe("claude-prod")

    assert status == "ok"
    assert method == "cli"
    claude_mock.assert_awaited_once()


# ───────────────────────────────────────────────────────────────────────
# (3) R17.2 — objective mode must surface the backend's real failure
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_objective_mode_surfaces_backend_error_when_draft_status_error(live_mcp):
    """When /ops/generate-plan persists a draft with status='error' and a
    populated 'error' field, gimo_generate_team_config MUST surface that
    real reason instead of the generic 'Plan not found or empty' message."""
    import json as _json

    fn = live_mcp._tool_manager._tools["gimo_generate_team_config"].fn

    create_response = "✅ Success (201):\n" + _json.dumps({"id": "d_err"})
    error_draft = {
        "id": "d_err",
        "status": "error",
        "error": "Plan generation failed: provider timeout",
        "content": None,
    }
    get_response = "✅ Success (200):\n" + _json.dumps(error_draft)

    async def fake_proxy(method, path, **kwargs):
        if method == "POST" and path == "/ops/generate-plan":
            return create_response
        if method == "GET" and path == "/ops/drafts/d_err":
            return get_response
        return "✅ Success (200):\n{}"

    with patch(
        "tools.gimo_server.mcp_bridge.bridge.proxy_to_api",
        side_effect=fake_proxy,
    ):
        result = await fn(objective="Build something that times out")

    parsed = _json.loads(result)
    assert "Plan not found or empty" not in parsed.get("error", ""), (
        "R17.2 regression: objective mode hid the real backend error"
    )
    assert "provider timeout" in parsed["error"]
    assert parsed.get("draft_status") == "error"
    assert parsed.get("draft_id") == "d_err"


@pytest.mark.asyncio
async def test_auth_probe_legacy_id_fallback_when_no_entry():
    """When no entry exists in cfg, the legacy ID-based heuristic still
    routes 'codex-account' to CodexAuthService for backwards compat."""
    empty_cfg = ProviderConfig(active="x", providers={})
    with patch(
        "tools.gimo_server.services.providers.service.ProviderService.get_config",
        return_value=empty_cfg,
    ), patch(
        "tools.gimo_server.services.codex_auth_service.CodexAuthService.get_auth_status",
        new=AsyncMock(return_value={"authenticated": True, "method": "cli"}),
    ) as codex_mock:
        status, _, _ = await ProviderDiagnosticsService._auth_probe("codex-account")

    assert status == "ok"
    codex_mock.assert_awaited_once()
