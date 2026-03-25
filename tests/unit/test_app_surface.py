import pytest
import json
from tools.gimo_server.app_mcp.server import mcp
from tools.gimo_server.services.app_session_service import AppSessionService

@pytest.mark.anyio
async def test_mcp_tools_registration():
    """P4: Verifica que las herramientas de la superficie App estén registradas."""
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "create_app_session" in tool_names
    assert "select_app_repo" in tool_names
    assert "list_app_repos" in tool_names

@pytest.mark.anyio
async def test_mcp_resources_registration():
    """P4: Verifica que los recursos de la superficie App estén registrados."""
    resources = await mcp.list_resources()
    # Verificamos que existan los recursos mínimos requeridos
    uris = [str(r.uri) for r in resources]
    assert "gimo://app/review/summary" in uris
    assert "gimo://app/diff/summary" in uris
    assert "gimo://app/logs/summary" in uris

@pytest.mark.anyio
async def test_create_app_session_tool():
    """P4: Prueba la herramienta de creación de sesión a través de MCP."""
    # Obtenemos el objeto de la herramienta y lo llamamos
    tool_func = None
    tools = await mcp.list_tools()
    for t in tools:
        if t.name == "create_app_session":
            # FastMCP call_tool convenient wrapper
            res = await mcp.call_tool("create_app_session", {"metadata": {"mcp": "test"}})
            # La respuesta de FastMCP suele estar en .content[0].text si devuelve un dict/str
            data = json.loads(res[0].text)
            assert "id" in data
            assert data["metadata"]["mcp"] == "test"
            AppSessionService.purge_session(data["id"])
            return
    pytest.fail("Tool create_app_session not found")

@pytest.mark.anyio
async def test_app_surface_does_not_leak_paths():
    """P4: Verifica que la superficie de App no expone host paths."""
    # En algunos entornos de prueba, call_tool puede devolver el resultado directamente 
    # o envuelto en una lista de objetos de contenido.
    res = await mcp.call_tool("list_app_repos", {})
    
    repos = []
    if isinstance(res, list) and len(res) > 0 and hasattr(res[0], "text"):
        # Si es una lista de TextContent (comportamiento estándar de MCP)
        try:
            repos = json.loads(res[0].text)
        except (json.JSONDecodeError, TypeError):
            import ast
            try:
                repos = ast.literal_eval(res[0].text)
            except:
                repos = res[0].text
    else:
        # Si FastMCP devolvió el objeto directo en el test
        repos = res

    # Si es un solo dict, lo metemos en una lista para el bucle
    if isinstance(repos, dict):
        repos = [repos]
    # Si sigue siendo un string, intentamos parsearlo
    elif isinstance(repos, str):
        try:
            repos = json.loads(repos)
        except:
            import ast
            try:
                repos = ast.literal_eval(repos)
            except:
                repos = []

    assert isinstance(repos, list), f"Se esperaba una lista de repositorios, se obtuvo {type(repos)}: {repos}"

    for repo in repos:
        assert isinstance(repo, dict), f"Cada repositorio debe ser un dict, se obtuvo {type(repo)}: {repo}"
        handle = repo["repo_id"]
        # El handle debe ser opaco (hash de 12 chars), no una ruta.
        assert len(handle) == 12
        assert ":" not in handle
        assert "\\" not in handle
        assert "/" not in handle
