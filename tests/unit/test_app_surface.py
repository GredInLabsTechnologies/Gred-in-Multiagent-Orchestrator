import json
from unittest.mock import patch

import pytest

from tools.gimo_server.app_mcp.server import create_app_mcp, mcp
from tools.gimo_server.app_mcp.tools import ALL_TOOL_NAMES, EXTENDED_ONLY_TOOL_NAMES, SAFE_TOOL_NAMES
from tools.gimo_server.main import app
from tools.gimo_server.services.app_session_service import AppSessionService


class _Dumpable:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


def _parse_text_payload(payload):
    if isinstance(payload, tuple) and len(payload) == 2:
        content, metadata = payload
        if isinstance(metadata, dict) and "result" in metadata:
            return metadata["result"]
        payload = content
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
async def test_mcp_tools_registration_safe_profile():
    tools = await mcp.list_tools()
    tool_names = {tool.name for tool in tools}
    assert tool_names == SAFE_TOOL_NAMES
    assert tool_names.isdisjoint(EXTENDED_ONLY_TOOL_NAMES)


@pytest.mark.anyio
async def test_mcp_tools_registration_extended_profile():
    extended_mcp = create_app_mcp("extended")
    tools = await extended_mcp.list_tools()
    tool_names = {tool.name for tool in tools}
    assert tool_names == ALL_TOOL_NAMES


@pytest.mark.anyio
async def test_mcp_tool_metadata_hints_are_explicit():
    safe_tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert safe_tools["create_app_session"].description.startswith("Use this when")
    assert safe_tools["get_app_run_review"].description.startswith("Use this when")
    assert safe_tools["create_app_session"].annotations.readOnlyHint is False
    assert safe_tools["create_app_session"].annotations.destructiveHint is False
    assert safe_tools["create_app_session"].annotations.openWorldHint is False
    assert safe_tools["get_app_run_review"].annotations.readOnlyHint is True
    assert safe_tools["get_app_run_review"].annotations.destructiveHint is False
    assert safe_tools["get_app_run_review"].annotations.openWorldHint is False

    extended_mcp = create_app_mcp("extended")
    extended_tools = {tool.name: tool for tool in await extended_mcp.list_tools()}
    assert extended_tools["discard_app_run"].description.startswith("Use this when")
    assert extended_tools["discard_app_run"].annotations.readOnlyHint is False
    assert extended_tools["discard_app_run"].annotations.destructiveHint is True
    assert extended_tools["discard_app_run"].annotations.openWorldHint is False


@pytest.mark.anyio
async def test_mcp_resources_registration():
    resources = await mcp.list_resources()
    uris = [str(resource.uri) for resource in resources]
    assert "gimo://app/repos" in uris

    templates = await mcp.list_resource_templates()
    template_uris = [template.uriTemplate for template in templates]
    assert "gimo://app/session/{session_id}" in template_uris
    assert "gimo://app/context-requests/{session_id}" in template_uris
    assert "gimo://app/review/{run_id}" in template_uris


def test_official_app_facade_mount_exposes_dual_transport_routes():
    mount_paths = [getattr(route, "path", None) for route in app.routes]
    assert "/mcp/app" in mount_paths

    official_mount = next(route for route in app.routes if getattr(route, "path", None) == "/mcp/app")
    subpaths = {getattr(route, "path", None) for route in official_mount.app.routes}
    assert {"/sse", "/messages", "/mcp"}.issubset(subpaths)


@pytest.mark.anyio
async def test_app_mcp_safe_roundtrip_covers_session_repo_recon_and_review(app_registered_repo):
    expected_handle = app_registered_repo["repo_id"]

    created = _parse_text_payload(await mcp.call_tool("create_app_session", {"metadata": {"mcp": "safe"}}))
    session_id = created["id"]
    assert created["metadata"]["mcp"] == "safe"
    assert created["metadata"]["surface"] == "chatgpt_app"
    assert created["metadata"]["workspace_mode"] == "ephemeral"
    assert created["metadata"]["orchestrator_authority"] == "chatgpt_app"
    assert created["metadata"]["orchestrator_selection_allowed"] is False
    assert created["metadata"]["worker_model_selection_allowed"] is False

    fetched = _parse_text_payload(await mcp.call_tool("get_app_session", {"session_id": session_id}))
    assert fetched["id"] == session_id
    assert fetched["repo_id"] is None

    repos = _parse_text_payload(await mcp.call_tool("list_app_repos", {}))
    assert any(repo["repo_id"] == expected_handle for repo in repos)

    repos_resource = _parse_text_payload(await mcp.read_resource("gimo://app/repos"))
    assert any(repo["repo_id"] == expected_handle for repo in repos_resource)

    selected = _parse_text_payload(
        await mcp.call_tool("select_app_repo", {"session_id": session_id, "repo_id": expected_handle})
    )
    assert selected == {"status": "ok", "repo_id": expected_handle}

    session_resource = _parse_text_payload(await mcp.read_resource(f"gimo://app/session/{session_id}"))
    assert session_resource["id"] == session_id
    assert session_resource["repo_id"] == expected_handle

    listing = _parse_text_payload(await mcp.call_tool("list_app_files", {"session_id": session_id}))
    assert listing["status"] == "ok"
    file_entry = next(entry for entry in listing["entries"] if entry["name"] == "app.py")

    search_payload = _parse_text_payload(
        await mcp.call_tool("search_app_repo", {"session_id": session_id, "query": "hello"})
    )
    assert search_payload["status"] == "ok"
    assert search_payload["results"]

    read_payload = _parse_text_payload(
        await mcp.call_tool("read_app_file", {"session_id": session_id, "file_handle": file_entry["handle"]})
    )
    assert read_payload["status"] == "ok"
    assert "print('hello')" in read_payload["content"]
    assert read_payload["proof"]["kind"] == "read"

    requests_payload = _parse_text_payload(
        await mcp.call_tool("list_app_context_requests", {"session_id": session_id})
    )
    assert requests_payload == {"status": "ok", "requests": []}

    with patch(
        "tools.gimo_server.app_mcp.tools.ReviewMergeService.get_merge_preview",
        return_value=_Dumpable({"run_id": "run-1", "can_merge": False}),
    ), patch(
        "tools.gimo_server.app_mcp.tools.ReviewMergeService.build_review_bundle",
        return_value=_Dumpable({"run_id": "run-1", "changed_files": ["app.py"]}),
    ):
        review_payload = _parse_text_payload(await mcp.call_tool("get_app_run_review", {"run_id": "run-1"}))

    assert review_payload["status"] == "ok"
    assert review_payload["preview"]["run_id"] == "run-1"
    assert review_payload["bundle"]["changed_files"] == ["app.py"]


@pytest.mark.anyio
async def test_app_surface_does_not_leak_paths(app_registered_repo):
    repos = _parse_text_payload(await mcp.call_tool("list_app_repos", {}))
    if isinstance(repos, dict) and "repo_id" in repos:
        repos = [repos]
    assert isinstance(repos, list)

    host_paths = set(AppSessionService.get_handle_mapping().values())
    for repo in repos:
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


@pytest.mark.anyio
async def test_app_mcp_extended_roundtrip_covers_mutating_tools(app_registered_repo):
    extended_mcp = create_app_mcp("extended")
    expected_handle = app_registered_repo["repo_id"]

    created = _parse_text_payload(
        await extended_mcp.call_tool("create_app_session", {"metadata": {"mcp": "extended"}})
    )
    session_id = created["id"]

    selected = _parse_text_payload(
        await extended_mcp.call_tool("select_app_repo", {"session_id": session_id, "repo_id": expected_handle})
    )
    assert selected == {"status": "ok", "repo_id": expected_handle}

    listing = _parse_text_payload(await extended_mcp.call_tool("list_app_files", {"session_id": session_id}))
    file_entry = next(entry for entry in listing["entries"] if entry["name"] == "app.py")

    _parse_text_payload(
        await extended_mcp.call_tool("read_app_file", {"session_id": session_id, "file_handle": file_entry["handle"]})
    )

    draft_payload = _parse_text_payload(
        await extended_mcp.call_tool(
            "create_validated_app_draft",
            {
                "session_id": session_id,
                "acceptance_criteria": "Confirm the app.py file was read.",
                "allowed_paths": ["app.py"],
            },
        )
    )
    assert draft_payload["status"] == "ok"
    assert draft_payload["validated_task_spec"]["allowed_paths"] == ["app.py"]

    request_payload = _parse_text_payload(
        await extended_mcp.call_tool(
            "create_app_context_request",
            {"session_id": session_id, "description": "Need clarification", "metadata": {"kind": "question"}},
        )
    )
    assert request_payload["status"] == "ok"
    request_id = request_payload["request"]["id"]

    resolved_payload = _parse_text_payload(
        await extended_mcp.call_tool(
            "resolve_app_context_request",
            {"session_id": session_id, "request_id": request_id, "evidence": "Resolved by operator"},
        )
    )
    assert resolved_payload == {"status": "ok", "request_id": request_id}

    with patch(
        "tools.gimo_server.app_mcp.tools.OpsService.discard_run",
        return_value=_Dumpable({"run_id": "run-2", "status": "discarded"}),
    ):
        discard_payload = _parse_text_payload(await extended_mcp.call_tool("discard_app_run", {"run_id": "run-2"}))

    assert discard_payload["status"] == "ok"
    assert discard_payload["receipt"]["status"] == "discarded"

    purged = _parse_text_payload(await extended_mcp.call_tool("purge_app_session", {"session_id": session_id}))
    assert purged == {"status": "ok", "deleted": session_id}

    missing = _parse_text_payload(await extended_mcp.call_tool("get_app_session", {"session_id": session_id}))
    assert missing["status"] == "error"
    assert missing["msg"] == "Session not found"
