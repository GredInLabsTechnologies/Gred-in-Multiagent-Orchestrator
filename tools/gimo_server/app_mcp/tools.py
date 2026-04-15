from __future__ import annotations

from typing import Awaitable, Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from tools.gimo_server.config import APP_MCP_ALLOWED_PROFILES
from tools.gimo_server.services.app_draft_service import AppDraftService
from tools.gimo_server.services.app_session_service import AppSessionService
from tools.gimo_server.services.context_request_service import ContextRequestService
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.workspace.repo_recon_service import RepoReconService
from tools.gimo_server.services.review_merge_service import ReviewMergeService

SAFE_TOOL_NAMES = frozenset(
    {
        "create_app_session",
        "get_app_session",
        "list_app_repos",
        "select_app_repo",
        "list_app_files",
        "search_app_repo",
        "read_app_file",
        "list_app_context_requests",
        "get_app_run_review",
    }
)
EXTENDED_ONLY_TOOL_NAMES = frozenset(
    {
        "create_validated_app_draft",
        "create_app_context_request",
        "resolve_app_context_request",
        "discard_app_run",
        "purge_app_session",
    }
)
ALL_TOOL_NAMES = SAFE_TOOL_NAMES | EXTENDED_ONLY_TOOL_NAMES

ToolHandler = Callable[..., Awaitable[object]]


def normalize_app_mcp_profile(profile: str | None) -> str:
    normalized = str(profile or "safe").strip().lower() or "safe"
    if normalized not in APP_MCP_ALLOWED_PROFILES:
        allowed = ", ".join(APP_MCP_ALLOWED_PROFILES)
        raise ValueError(f"Unsupported App MCP profile '{profile}'. Expected one of: {allowed}")
    return normalized


def _list_repo_handles() -> list[dict[str, str]]:
    return [{"repo_id": handle} for handle in AppSessionService.get_handle_mapping().keys()]


def _tool_annotations(
    *,
    title: str,
    read_only: bool,
    destructive: bool = False,
    open_world: bool = False,
) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        readOnlyHint=read_only,
        destructiveHint=destructive,
        openWorldHint=open_world,
    )


def _register_tool(
    mcp: FastMCP,
    *,
    name: str,
    description: str,
    annotations: ToolAnnotations,
    handler: ToolHandler,
) -> None:
    mcp.tool(name=name, description=description, annotations=annotations)(handler)


def register_tools(mcp: FastMCP, *, profile: str = "safe") -> None:
    normalized_profile = normalize_app_mcp_profile(profile)
    include_extended = normalized_profile == "extended"

    async def create_app_session(metadata: dict | None = None) -> dict:
        return AppSessionService.create_session(metadata)

    _register_tool(
        mcp,
        name="create_app_session",
        description=(
            "Use this when you need to start a new GIMO App session before selecting a repository. "
            "Do not use this to change repository contents or run lifecycle state."
        ),
        annotations=_tool_annotations(
            title="Create App Session",
            read_only=False,
            destructive=False,
            open_world=False,
        ),
        handler=create_app_session,
    )

    async def get_app_session(session_id: str) -> dict:
        session = AppSessionService.get_session(session_id)
        if session:
            return session
        return {"status": "error", "msg": "Session not found", "session_id": session_id}

    _register_tool(
        mcp,
        name="get_app_session",
        description=(
            "Use this when you need the canonical state of an existing GIMO App session. "
            "Do not use this to discover repositories or file contents."
        ),
        annotations=_tool_annotations(
            title="Get App Session",
            read_only=True,
            destructive=False,
            open_world=False,
        ),
        handler=get_app_session,
    )

    async def list_app_repos() -> list[dict[str, str]]:
        return _list_repo_handles()

    _register_tool(
        mcp,
        name="list_app_repos",
        description=(
            "Use this when you need the available opaque repository handles for a new or existing "
            "App session. Do not use this to inspect host paths."
        ),
        annotations=_tool_annotations(
            title="List App Repositories",
            read_only=True,
            destructive=False,
            open_world=False,
        ),
        handler=list_app_repos,
    )

    async def select_app_repo(session_id: str, repo_id: str) -> dict:
        if AppSessionService.bind_repo(session_id, repo_id):
            return {"status": "ok", "repo_id": repo_id}
        return {"status": "error", "msg": "Invalid session or repo_id"}

    _register_tool(
        mcp,
        name="select_app_repo",
        description=(
            "Use this when you need to bind one opaque repository handle to an App session before "
            "reconnaissance. Do not use this to access host paths or choose orchestrator authority."
        ),
        annotations=_tool_annotations(
            title="Select App Repository",
            read_only=False,
            destructive=False,
            open_world=False,
        ),
        handler=select_app_repo,
    )

    async def list_app_files(session_id: str, path_handle: str | None = None) -> dict:
        try:
            return {"status": "ok", "entries": RepoReconService.list_files(session_id, path_handle)}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    _register_tool(
        mcp,
        name="list_app_files",
        description=(
            "Use this when you need directory entries from the repository bound to the current App "
            "session. Do not use this to read file contents."
        ),
        annotations=_tool_annotations(
            title="List App Files",
            read_only=True,
            destructive=False,
            open_world=False,
        ),
        handler=list_app_files,
    )

    async def search_app_repo(session_id: str, query: str) -> dict:
        try:
            return {"status": "ok", "results": RepoReconService.search(session_id, query)}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    _register_tool(
        mcp,
        name="search_app_repo",
        description=(
            "Use this when you need to find strings, symbols, or implementation references inside the "
            "repository bound to the current App session. Do not use this to read whole files."
        ),
        annotations=_tool_annotations(
            title="Search App Repository",
            read_only=True,
            destructive=False,
            open_world=False,
        ),
        handler=search_app_repo,
    )

    async def read_app_file(session_id: str, file_handle: str) -> dict:
        try:
            return {"status": "ok", **RepoReconService.read_file(session_id, file_handle)}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    _register_tool(
        mcp,
        name="read_app_file",
        description=(
            "Use this when you need the full contents of a file that was already discovered through "
            "listing or search. Do not use this to browse large areas of the repository."
        ),
        annotations=_tool_annotations(
            title="Read App File",
            read_only=True,
            destructive=False,
            open_world=False,
        ),
        handler=read_app_file,
    )

    async def list_app_context_requests(session_id: str, status_filter: str | None = None) -> dict:
        try:
            requests = ContextRequestService.list_requests(session_id, status_filter)
            return {"status": "ok", "requests": requests}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    _register_tool(
        mcp,
        name="list_app_context_requests",
        description=(
            "Use this when you need to inspect persistent context requests that already exist for the "
            "current App session. Do not use this to create or resolve requests."
        ),
        annotations=_tool_annotations(
            title="List App Context Requests",
            read_only=True,
            destructive=False,
            open_world=False,
        ),
        handler=list_app_context_requests,
    )

    async def get_app_run_review(run_id: str) -> dict:
        try:
            return {
                "status": "ok",
                "preview": ReviewMergeService.get_merge_preview(run_id).model_dump(),
                "bundle": ReviewMergeService.build_review_bundle(run_id).model_dump(),
            }
        except Exception as exc:
            return {"status": "error", "msg": str(exc), "run_id": run_id}

    _register_tool(
        mcp,
        name="get_app_run_review",
        description=(
            "Use this when you need the canonical review bundle and merge preview for an App run. "
            "Do not use this to execute, merge, or discard the run."
        ),
        annotations=_tool_annotations(
            title="Get App Run Review",
            read_only=True,
            destructive=False,
            open_world=False,
        ),
        handler=get_app_run_review,
    )

    if not include_extended:
        return

    async def create_validated_app_draft(
        session_id: str,
        acceptance_criteria: str,
        allowed_paths: list[str] | None = None,
    ) -> dict:
        payload: dict[str, object] = {
            "acceptance_criteria": acceptance_criteria,
            "allowed_paths": allowed_paths or [],
        }
        try:
            result = AppDraftService.create_validated_draft(session_id, payload)
            return {"status": "ok", **result.model_dump()}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    _register_tool(
        mcp,
        name="create_validated_app_draft",
        description=(
            "Use this when you need to create a validated draft after reconnaissance evidence has "
            "already been recorded for the current App session. Do not use this before reading the "
            "relevant files."
        ),
        annotations=_tool_annotations(
            title="Create Validated App Draft",
            read_only=False,
            destructive=False,
            open_world=False,
        ),
        handler=create_validated_app_draft,
    )

    async def create_app_context_request(
        session_id: str,
        description: str,
        metadata: dict | None = None,
    ) -> dict:
        try:
            request = ContextRequestService.create_request(session_id, description, metadata)
            return {"status": "ok", "request": request}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    _register_tool(
        mcp,
        name="create_app_context_request",
        description=(
            "Use this when required context is missing and you need to persist a follow-up request for "
            "the current App session. Do not use this if the answer is already available from repo recon."
        ),
        annotations=_tool_annotations(
            title="Create App Context Request",
            read_only=False,
            destructive=False,
            open_world=False,
        ),
        handler=create_app_context_request,
    )

    async def resolve_app_context_request(session_id: str, request_id: str, evidence: str) -> dict:
        if ContextRequestService.resolve_request(session_id, request_id, evidence):
            return {"status": "ok", "request_id": request_id}
        return {"status": "error", "msg": "Request not found", "request_id": request_id}

    _register_tool(
        mcp,
        name="resolve_app_context_request",
        description=(
            "Use this when the user or operator has supplied the missing evidence for an existing App "
            "context request. Do not use this to invent or summarize missing information."
        ),
        annotations=_tool_annotations(
            title="Resolve App Context Request",
            read_only=False,
            destructive=False,
            open_world=False,
        ),
        handler=resolve_app_context_request,
    )

    async def discard_app_run(run_id: str) -> dict:
        try:
            receipt = OpsService.discard_run(run_id)
            return {"status": "ok", "receipt": receipt.model_dump()}
        except Exception as exc:
            return {"status": "error", "msg": str(exc), "run_id": run_id}

    _register_tool(
        mcp,
        name="discard_app_run",
        description=(
            "Use this when the user explicitly wants to discard an App run and purge reconstructive "
            "state. Do not use this as a retry shortcut or as a merge action."
        ),
        annotations=_tool_annotations(
            title="Discard App Run",
            read_only=False,
            destructive=True,
            open_world=False,
        ),
        handler=discard_app_run,
    )

    async def purge_app_session(session_id: str) -> dict:
        if AppSessionService.purge_session(session_id):
            return {"status": "ok", "deleted": session_id}
        return {"status": "error", "msg": "Session not found", "session_id": session_id}

    _register_tool(
        mcp,
        name="purge_app_session",
        description=(
            "Use this when an App session is no longer needed and should be deleted. Do not use this to "
            "reset repository state in the middle of a workflow."
        ),
        annotations=_tool_annotations(
            title="Purge App Session",
            read_only=False,
            destructive=True,
            open_world=False,
        ),
        handler=purge_app_session,
    )
