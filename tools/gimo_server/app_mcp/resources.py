import json

from mcp.server.fastmcp import FastMCP
from tools.gimo_server.services.app_session_service import AppSessionService


def register_resources(mcp: FastMCP):
    @mcp.resource("gimo://app/session/{session_id}")
    async def get_session_overview(session_id: str) -> str:
        """P4: Obtiene el estado canónico de una sesión de App."""
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
        """P4: Lista los repositorios disponibles mediante handles opacos."""
        return json.dumps(
            [{"repo_id": handle} for handle in AppSessionService.get_handle_mapping().keys()],
            indent=2,
        )
