from mcp.server.fastmcp import FastMCP
from tools.gimo_server.services.app_session_service import AppSessionService

def register_tools(mcp: FastMCP):
    @mcp.tool()
    async def create_app_session(metadata: dict = None) -> dict:
        """Crea una nueva sesión para ChatGPT Apps."""
        return AppSessionService.create_session(metadata)

    @mcp.tool()
    async def select_app_repo(session_id: str, repo_id: str) -> dict:
        """Selecciona un repositorio usando su handle opaco (repo_id)."""
        if AppSessionService.bind_repo(session_id, repo_id):
            return {"status": "ok", "repo_id": repo_id}
        return {"status": "error", "msg": "Sesión o repo_id no válidos"}

    @mcp.tool()
    async def list_app_repos() -> list:
        """Lista los repositorios disponibles mediante sus handles opacos (seguro)."""
        mapping = AppSessionService.get_handle_mapping()
        # Solo retornamos los handles para no filtrar host paths.
        return [{"repo_id": handle} for handle in mapping.keys()]
