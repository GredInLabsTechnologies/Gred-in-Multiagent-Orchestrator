from mcp.server.fastmcp import FastMCP
from tools.gimo_server.services.app_session_service import AppSessionService

def register_resources(mcp: FastMCP):
    @mcp.resource("gimo://app/session/{session_id}")
    async def get_session_overview(session_id: str) -> str:
        """P4: Obtiene un resumen de la sesión de App actual."""
        session = AppSessionService.get_session(session_id)
        if not session:
            return "Session not found."
        handle_str = session.get('repo_id') or 'None'
        return f"ID: {session['id']}\nStatus: {session['status']}\nBound Repo Handle: {handle_str}\nCreated: {session['created_at']}"

    @mcp.resource("gimo://app/review/summary")
    async def get_review_summary() -> str:
        """P4 Honest Dummy: Resumen de revisión para App."""
        return "Review summary: No active reviews found via App surface."

    @mcp.resource("gimo://app/diff/summary")
    async def get_diff_summary() -> str:
        """P4 Honest Dummy: Resumen de diff para App."""
        return "Diff summary: No pending diffs available via App surface."

    @mcp.resource("gimo://app/logs/summary")
    async def get_logs_summary() -> str:
        """P4 Honest Dummy: Resumen de logs para App."""
        return "Logs summary: No logs available for the current app session."
