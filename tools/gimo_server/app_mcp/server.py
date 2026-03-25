import logging
from mcp.server.fastmcp import FastMCP
from tools.gimo_server.app_mcp.tools import register_tools
from tools.gimo_server.app_mcp.resources import register_resources

logger = logging.getLogger("app_mcp.server")

# Inicializa FastMCP para ChatGPT Apps
# Usamos un nombre distintivo para evitar colisión con el bridge legado.
mcp = FastMCP("GIMO-App", dependencies=["httpx", "uvicorn", "fastapi"])

register_tools(mcp)
register_resources(mcp)
