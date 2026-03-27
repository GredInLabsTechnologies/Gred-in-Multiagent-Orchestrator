import json

from mcp.server.fastmcp import FastMCP

from tools.gimo_server.services.app_session_service import AppSessionService
from tools.gimo_server.services.context_request_service import ContextRequestService
from tools.gimo_server.services.review_merge_service import ReviewMergeService


def register_resources(mcp: FastMCP):
    @mcp.resource("gimo://app/session/{session_id}")
    async def get_session_overview(session_id: str) -> str:
        """Return the canonical state of an App session."""
        session = AppSessionService.get_session(session_id)
        if not session:
            return json.dumps({"status": "error", "msg": "Session not found", "session_id": session_id}, indent=2)
        return json.dumps(
            {
                "id": session["id"],
                "status": session["status"],
                "repo_id": session.get("repo_id"),
                "created_at": session["created_at"],
                "updated_at": session["updated_at"],
                "metadata": session.get("metadata", {}),
            },
            indent=2,
        )

    @mcp.resource("gimo://app/repos")
    async def get_repo_handles() -> str:
        """List the available repositories through opaque handles."""
        return json.dumps(
            [{"repo_id": handle} for handle in AppSessionService.get_handle_mapping().keys()],
            indent=2,
        )

    @mcp.resource("gimo://app/context-requests/{session_id}")
    async def get_context_requests(session_id: str) -> str:
        """Return the persisted context requests for a session."""
        return json.dumps(
            {
                "session_id": session_id,
                "requests": ContextRequestService.get_request_history(session_id),
            },
            indent=2,
        )

    @mcp.resource("gimo://app/review/{run_id}")
    async def get_review_summary(run_id: str) -> str:
        """Return a compact canonical review summary for a run."""
        preview = ReviewMergeService.get_merge_preview(run_id).model_dump()
        bundle = ReviewMergeService.build_review_bundle(run_id).model_dump()
        return json.dumps(
            {
                "run_id": run_id,
                "preview": preview,
                "summary": {
                    "changed_files": bundle.get("changed_files", []),
                    "drift_detected": bundle.get("drift_detected", False),
                    "test_evidence": bundle.get("test_evidence"),
                    "lint_evidence": bundle.get("lint_evidence"),
                },
            },
            indent=2,
        )
