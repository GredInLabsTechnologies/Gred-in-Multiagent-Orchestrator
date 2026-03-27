import json
from unittest.mock import patch

import pytest

import gimo
from gimo import _handle_chat_slash_command
from gimo_tui import GimoApp
from tools.gimo_server.app_mcp.server import mcp
from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.app_session_service import AppSessionService


def _auth(role: str):
    return lambda: AuthContext(token="t", role=role)


def _parse_text_payload(payload):
    if isinstance(payload, list) and payload and hasattr(payload[0], "text"):
        parsed = [json.loads(item.text) for item in payload]
        return parsed[0] if len(parsed) == 1 else parsed
    if isinstance(payload, list) and payload and hasattr(payload[0], "content"):
        return json.loads(payload[0].content)
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def _static_content(widget) -> str:
    return str(getattr(widget, "content", widget.render()))


@pytest.mark.anyio
async def test_cli_and_tui_consume_same_operator_status_contract():
    snapshot = {
        "repo": "repo",
        "branch": "main",
        "active_provider": "openai",
        "active_model": "gpt-5.4",
        "permissions": "full-auto",
        "budget_status": "low",
        "budget_percentage": 18.5,
        "context_status": "75%",
        "alerts": [
            {"level": "warning", "code": "ctx_high", "message": "Context usage is high (75.0%)"},
            {"level": "warning", "code": "budget_high", "message": "Budget usage is near limit (81.5% used)"},
        ],
    }

    cli_calls: list[tuple[str, str]] = []

    def _fake_cli_api_request(config, method, path, **kwargs):
        del config, kwargs
        cli_calls.append((method, path))
        return 200, snapshot

    with patch("gimo._api_request", side_effect=_fake_cli_api_request), patch.object(
        gimo.ConsoleTerminalSurface,
        "render_status_snapshot",
        autospec=True,
    ) as mock_render_status:
        handled, outcome = _handle_chat_slash_command(
            {"orchestrator": {}},
            "/status",
            workspace_root="C:/workspace",
            thread_id="thread-123",
        )

    assert handled is True
    assert outcome is None
    assert cli_calls == [("GET", "/ops/operator/status")]
    assert mock_render_status.call_args.args[1] == snapshot

    tui_calls: list[tuple[str, str]] = []

    def _fake_tui_api_request(config, method, path, **kwargs):
        del config, kwargs
        tui_calls.append((method, path))
        return 200, snapshot

    tui = GimoApp(
        config={"repository": {"workspace_root": "C:/workspace"}},
        thread_id="thread-123",
    )
    with patch("gimo_tui._api_request", side_effect=_fake_tui_api_request):
        async with tui.run_test() as pilot:
            tui_calls.clear()
            tui.action_refresh_all()
            await pilot.pause()

            header = _static_content(tui.query_one("#header-text"))
            notices = _static_content(tui.query_one("#notices-content"))

    assert tui_calls == [("GET", "/ops/operator/status")]
    assert "repo" in header
    assert "main" in header
    assert "gpt-5.4" in header
    assert "full-auto" in header
    assert "Context usage is high" in notices
    assert "Budget usage is near limit" in notices


@pytest.mark.anyio
async def test_app_rest_and_mcp_share_session_state_for_official_overlap(test_client):
    app.dependency_overrides[verify_token] = _auth("operator")

    handles = AppSessionService.get_handle_mapping()
    assert handles, "App surface requires at least one registered repo handle"
    repo_id = next(iter(handles.keys()))

    created = test_client.post("/ops/app/sessions", json={"metadata": {"created_via": "rest"}})
    assert created.status_code == 200
    session_id = created.json()["id"]

    fetched_via_mcp = _parse_text_payload(await mcp.call_tool("get_app_session", {"session_id": session_id}))
    assert fetched_via_mcp["id"] == session_id
    assert fetched_via_mcp["metadata"]["created_via"] == "rest"
    assert fetched_via_mcp["repo_id"] is None

    selected_via_mcp = _parse_text_payload(
        await mcp.call_tool("select_app_repo", {"session_id": session_id, "repo_id": repo_id})
    )
    assert selected_via_mcp == {"status": "ok", "repo_id": repo_id}

    fetched_via_rest = test_client.get(f"/ops/app/sessions/{session_id}")
    assert fetched_via_rest.status_code == 200
    assert fetched_via_rest.json()["repo_id"] == repo_id

    session_resource = _parse_text_payload(await mcp.read_resource(f"gimo://app/session/{session_id}"))
    assert session_resource["id"] == session_id
    assert session_resource["repo_id"] == repo_id

    purged = test_client.post(f"/ops/app/sessions/{session_id}/purge")
    assert purged.status_code == 200
    assert purged.json()["deleted"] == session_id

    missing_via_mcp = _parse_text_payload(await mcp.call_tool("get_app_session", {"session_id": session_id}))
    assert missing_via_mcp == {"status": "error", "msg": "Session not found", "session_id": session_id}


@pytest.mark.anyio
async def test_app_surface_map_is_honest_about_rest_vs_mcp_capabilities():
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/mcp/app" in route_paths
    assert "/ops/app/runs/{run_id}/review" in route_paths
    assert "/ops/app/runs/{run_id}/discard" in route_paths

    tool_names = {tool.name for tool in await mcp.list_tools()}
    assert {
        "create_app_session",
        "get_app_session",
        "select_app_repo",
        "list_app_repos",
        "purge_app_session",
    }.issubset(tool_names)
    assert not any(name for name in tool_names if "review" in name or "discard" in name or "execute" in name)

    resource_uris = {str(resource.uri) for resource in await mcp.list_resources()}
    template_uris = {template.uriTemplate for template in await mcp.list_resource_templates()}
    assert resource_uris == {"gimo://app/repos"}
    assert template_uris == {"gimo://app/session/{session_id}"}


def test_legacy_path_deprecations():
    from tools.gimo_server.ops_routes import get_filtered_openapi
    from tools.gimo_server.routers.ops.repo_router import open_repo, select_repo

    assert "[LEGACY INTEGRATION]" in (get_filtered_openapi.__doc__ or "")
    assert "[LEGACY]" in (open_repo.__doc__ or "")
    assert "[LEGACY]" in (select_repo.__doc__ or "")
