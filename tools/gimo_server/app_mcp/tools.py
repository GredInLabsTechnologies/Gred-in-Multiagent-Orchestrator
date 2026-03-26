from mcp.server.fastmcp import FastMCP
from tools.gimo_server.services.app_session_service import AppSessionService


def _list_repo_handles() -> list[dict[str, str]]:
    return [{"repo_id": handle} for handle in AppSessionService.get_handle_mapping().keys()]


def register_tools(mcp: FastMCP):
    @mcp.tool()
    async def create_app_session(metadata: dict = None) -> dict:
        """Crea una nueva sesión para ChatGPT Apps."""
        return AppSessionService.create_session(metadata)

    @mcp.tool()
    async def get_app_session(session_id: str) -> dict:
        """Recupera una sesión de App existente."""
        session = AppSessionService.get_session(session_id)
        if session:
            return session
        return {"status": "error", "msg": "Session not found", "session_id": session_id}

    @mcp.tool()
    async def select_app_repo(session_id: str, repo_id: str) -> dict:
        """Selecciona un repositorio usando su handle opaco (repo_id)."""
        if AppSessionService.bind_repo(session_id, repo_id):
            return {"status": "ok", "repo_id": repo_id}
        return {"status": "error", "msg": "Sesión o repo_id no válidos"}

    @mcp.tool()
    async def list_app_repos() -> list:
        """Lista los repositorios disponibles mediante sus handles opacos (seguro)."""
        return _list_repo_handles()

    @mcp.tool()
    async def purge_app_session(session_id: str) -> dict:
        """Elimina una sesión de App existente."""
        if AppSessionService.purge_session(session_id):
            return {"status": "ok", "deleted": session_id}
        return {"status": "error", "msg": "Session not found", "session_id": session_id}
