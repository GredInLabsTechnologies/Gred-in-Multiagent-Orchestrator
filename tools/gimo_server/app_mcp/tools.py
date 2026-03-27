from mcp.server.fastmcp import FastMCP

from tools.gimo_server.services.app_session_service import AppSessionService
from tools.gimo_server.services.context_request_service import ContextRequestService
from tools.gimo_server.services.draft_validation_service import DraftValidationService
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.repo_recon_service import RepoReconService
from tools.gimo_server.services.review_merge_service import ReviewMergeService


def _list_repo_handles() -> list[dict[str, str]]:
    return [{"repo_id": handle} for handle in AppSessionService.get_handle_mapping().keys()]


def register_tools(mcp: FastMCP):
    @mcp.tool()
    async def create_app_session(metadata: dict = None) -> dict:
        """Create a new App session."""
        return AppSessionService.create_session(metadata)

    @mcp.tool()
    async def get_app_session(session_id: str) -> dict:
        """Fetch an existing App session."""
        session = AppSessionService.get_session(session_id)
        if session:
            return session
        return {"status": "error", "msg": "Session not found", "session_id": session_id}

    @mcp.tool()
    async def select_app_repo(session_id: str, repo_id: str) -> dict:
        """Bind a repository through its opaque repo handle."""
        if AppSessionService.bind_repo(session_id, repo_id):
            return {"status": "ok", "repo_id": repo_id}
        return {"status": "error", "msg": "Invalid session or repo_id"}

    @mcp.tool()
    async def list_app_repos() -> list:
        """List available repositories through opaque handles only."""
        return _list_repo_handles()

    @mcp.tool()
    async def purge_app_session(session_id: str) -> dict:
        """Delete an existing App session."""
        if AppSessionService.purge_session(session_id):
            return {"status": "ok", "deleted": session_id}
        return {"status": "error", "msg": "Session not found", "session_id": session_id}

    @mcp.tool()
    async def list_app_files(session_id: str, path_handle: str | None = None) -> dict:
        """List repository files using opaque handles."""
        try:
            return {"status": "ok", "entries": RepoReconService.list_files(session_id, path_handle)}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    @mcp.tool()
    async def search_app_repo(session_id: str, query: str) -> dict:
        """Search the bound repository without leaking host paths."""
        try:
            return {"status": "ok", "results": RepoReconService.search(session_id, query)}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    @mcp.tool()
    async def read_app_file(session_id: str, file_handle: str) -> dict:
        """Read a repository file and persist a ReadProof artifact."""
        try:
            return {"status": "ok", **RepoReconService.read_file(session_id, file_handle)}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    @mcp.tool()
    async def create_validated_app_draft(
        session_id: str,
        acceptance_criteria: str,
        allowed_paths: list[str] | None = None,
    ) -> dict:
        """Create a ValidatedTaskSpec from recon evidence already recorded.

        Worker model selection is resolved by backend authority, not by the App surface.
        """
        payload: dict[str, object] = {
            "acceptance_criteria": acceptance_criteria,
            "allowed_paths": allowed_paths or [],
        }
        try:
            result = DraftValidationService.validate_draft(session_id, payload)
            return {"status": "ok", **result}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    @mcp.tool()
    async def create_app_context_request(session_id: str, description: str, metadata: dict | None = None) -> dict:
        """Create a persistent request for additional context."""
        try:
            request = ContextRequestService.create_request(session_id, description, metadata)
            return {"status": "ok", "request": request}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    @mcp.tool()
    async def list_app_context_requests(session_id: str, status_filter: str | None = None) -> dict:
        """List persistent context requests for a session."""
        try:
            requests = ContextRequestService.list_requests(session_id, status_filter)
            return {"status": "ok", "requests": requests}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    @mcp.tool()
    async def resolve_app_context_request(session_id: str, request_id: str, evidence: str) -> dict:
        """Resolve a pending context request."""
        if ContextRequestService.resolve_request(session_id, request_id, evidence):
            return {"status": "ok", "request_id": request_id}
        return {"status": "error", "msg": "Request not found", "request_id": request_id}

    @mcp.tool()
    async def get_app_run_review(run_id: str) -> dict:
        """Return the canonical review bundle and merge preview for a run."""
        try:
            return {
                "status": "ok",
                "preview": ReviewMergeService.get_merge_preview(run_id).model_dump(),
                "bundle": ReviewMergeService.build_review_bundle(run_id).model_dump(),
            }
        except Exception as exc:
            return {"status": "error", "msg": str(exc), "run_id": run_id}

    @mcp.tool()
    async def discard_app_run(run_id: str) -> dict:
        """Discard a run and purge reconstructive state."""
        try:
            receipt = OpsService.discard_run(run_id)
            return {"status": "ok", "receipt": receipt.model_dump()}
        except Exception as exc:
            return {"status": "error", "msg": str(exc), "run_id": run_id}
