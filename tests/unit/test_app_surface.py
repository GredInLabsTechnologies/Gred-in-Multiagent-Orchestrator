import pytest
import json
from tools.gimo_server.main import app
from tools.gimo_server.app_mcp.server import mcp
from tools.gimo_server.services.app_session_service import AppSessionService


def _parse_text_payload(payload):
    if isinstance(payload, list) and payload and hasattr(payload[0], "text"):
        parsed = [json.loads(item.text) for item in payload]
        return parsed[0] if len(parsed) == 1 else parsed
    if isinstance(payload, list) and payload and hasattr(payload[0], "content"):
        parsed = json.loads(payload[0].content)
        return parsed
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


@pytest.mark.anyio
async def test_mcp_tools_registration():
    """P4: Verifica que las herramientas de la superficie App estén registradas."""
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "create_app_session" in tool_names
    assert "get_app_session" in tool_names
    assert "select_app_repo" in tool_names
    assert "list_app_repos" in tool_names
    assert "purge_app_session" in tool_names

@pytest.mark.anyio
async def test_mcp_resources_registration():
    """P4: Verifica que los recursos y templates de App estén registrados canónicamente."""
    resources = await mcp.list_resources()
    uris = [str(r.uri) for r in resources]
    assert "gimo://app/repos" in uris

    templates = await mcp.list_resource_templates()
    template_uris = [t.uriTemplate for t in templates]
    assert "gimo://app/session/{session_id}" in template_uris

def test_official_app_facade_is_mounted():
    """P4: Verifica que la fachada oficial esté montada en /mcp/app."""
    mount_paths = [getattr(route, "path", None) for route in app.routes]
    assert "/mcp/app" in mount_paths

@pytest.mark.anyio
async def test_app_mcp_lifecycle_roundtrip():
    """P4: Prueba create/get/select/purge y recursos canónicos a través de MCP."""
    mapping = AppSessionService.get_handle_mapping()
    assert mapping, "App surface requires at least one registered repo handle"
    expected_handle = next(iter(mapping.keys()))

    created = _parse_text_payload(
        await mcp.call_tool("create_app_session", {"metadata": {"mcp": "test"}})
    )
    session_id = created["id"]
    assert created["metadata"]["mcp"] == "test"

    fetched = _parse_text_payload(await mcp.call_tool("get_app_session", {"session_id": session_id}))
    assert fetched["id"] == session_id
    assert fetched["repo_id"] is None

    repos = _parse_text_payload(await mcp.read_resource("gimo://app/repos"))
    assert any(repo["repo_id"] == expected_handle for repo in repos)

    selected = _parse_text_payload(
        await mcp.call_tool("select_app_repo", {"session_id": session_id, "repo_id": expected_handle})
    )
    assert selected == {"status": "ok", "repo_id": expected_handle}

    session_resource = _parse_text_payload(await mcp.read_resource(f"gimo://app/session/{session_id}"))
    assert session_resource["id"] == session_id
    assert session_resource["repo_id"] == expected_handle

    purged = _parse_text_payload(await mcp.call_tool("purge_app_session", {"session_id": session_id}))
    assert purged == {"status": "ok", "deleted": session_id}

    missing = _parse_text_payload(await mcp.call_tool("get_app_session", {"session_id": session_id}))
    assert missing["status"] == "error"
    assert missing["msg"] == "Session not found"

@pytest.mark.anyio
async def test_app_surface_does_not_leak_paths():
    """P4: Verifica que la superficie de App no expone host paths."""
    repos = _parse_text_payload(await mcp.call_tool("list_app_repos", {}))
    assert isinstance(repos, list), f"Se esperaba una lista de repositorios, se obtuvo {type(repos)}: {repos}"

    host_paths = set(AppSessionService.get_handle_mapping().values())
    for repo in repos:
        assert isinstance(repo, dict), f"Cada repositorio debe ser un dict, se obtuvo {type(repo)}: {repo}"
        handle = repo["repo_id"]
        assert len(handle) == 12
        assert ":" not in handle
        assert "\\" not in handle
        assert "/" not in handle
        assert handle not in host_paths

    repos_resource = await mcp.read_resource("gimo://app/repos")
    serialized_resource = repos_resource[0].content
    for host_path in host_paths:
        assert host_path not in serialized_resource
