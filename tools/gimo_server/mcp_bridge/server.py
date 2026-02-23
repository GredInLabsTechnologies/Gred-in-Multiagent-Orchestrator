import asyncio
from mcp.server.fastmcp import FastMCP
from tools.gimo_server.config import get_settings
from tools.gimo_server.services.run_worker import RunWorker

# Initialize FastMCP Server
mcp = FastMCP("GIMO", dependencies=["httpx", "uvicorn", "fastapi"])

# Keep global references matching original architecture
_active_run_worker = None

def _register_dynamic():
    from tools.gimo_server.mcp_bridge.registrar import register_all
    from tools.gimo_server.mcp_bridge.resources import register_resources
    from tools.gimo_server.mcp_bridge.prompts import register_prompts
    
    register_all(mcp)
    register_resources(mcp)
    register_prompts(mcp)

def _register_native():
    from tools.gimo_server.mcp_bridge.native_tools import register_native_tools
    register_native_tools(mcp)

async def _startup_and_run() -> None:
    settings = get_settings()
    # Ensure dirs
    settings.ops_data_dir.mkdir(parents=True, exist_ok=True)
    for d in ["drafts", "approved", "runs", "threads"]:
        (settings.ops_data_dir / d).mkdir(parents=True, exist_ok=True)
    
    global _active_run_worker
    _active_run_worker = RunWorker()
    await _active_run_worker.start()
    
    _register_dynamic()
    _register_native()
    
    try:
        await mcp.run_stdio_async()
    finally:
        if _active_run_worker:
            await _active_run_worker.stop()

def main():
    asyncio.run(_startup_and_run())

if __name__ == "__main__":
    main()
