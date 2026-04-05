import asyncio
import logging
import socket
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from tools.gimo_server.config import get_settings

logger = logging.getLogger("mcp_bridge.server")

# Initialize FastMCP Server
mcp = FastMCP("GIMO", dependencies=["httpx", "uvicorn", "fastapi"])

# RunWorker instance managed by this bridge process (used by gimo_reload_worker)
_active_run_worker = None


def _is_backend_running() -> bool:
    """Check if GIMO HTTP backend is listening on port 9325."""
    try:
        with socket.create_connection(("127.0.0.1", 9325), timeout=0.5):
            return True
    except OSError:
        return False


def _auto_start_backend() -> None:
    """Start GIMO HTTP backend as a background subprocess if not already running."""
    if _is_backend_running():
        logger.info("GIMO backend already running on 127.0.0.1:9325")
        return

    root = Path(__file__).resolve().parents[3]
    python_exe = sys.executable
    for p in [".venv", "venv", "env"]:
        candidate = root / p / "Scripts" / "python.exe"
        if candidate.exists():
            python_exe = str(candidate)
            break

    # Ensure ORCH_TOKEN exists in .env before starting
    env_file = root / ".env"
    env_content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    if "ORCH_TOKEN=" not in env_content:
        import secrets
        token = secrets.token_hex(32)
        with open(env_file, "a", encoding="utf-8") as f:
            f.write(f"\nORCH_PORT=9325\nORCH_TOKEN={token}\n")
        ui_env = root / "tools" / "orchestrator_ui" / ".env.local"
        ui_env.parent.mkdir(parents=True, exist_ok=True)
        with open(ui_env, "w", encoding="utf-8") as f:
            f.write(f"VITE_ORCH_TOKEN={token}\n")

    try:
        subprocess.Popen(
            [
                python_exe, "-m", "uvicorn",
                "tools.gimo_server.main:app",
                "--host", "127.0.0.1",
                "--port", "9325",
                "--log-level", "warning",
            ],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("Auto-started GIMO backend on 127.0.0.1:9325")
    except Exception as exc:
        logger.warning("Failed to auto-start GIMO backend: %s", exc)


def _register_dynamic():
    from tools.gimo_server.mcp_bridge.registrar import register_all
    from tools.gimo_server.mcp_bridge.resources import register_resources
    from tools.gimo_server.mcp_bridge.prompts import register_prompts

    register_all(mcp)
    register_resources(mcp)
    register_prompts(mcp)


def _register_native():
    from tools.gimo_server.mcp_bridge.native_tools import register_native_tools
    from tools.gimo_server.mcp_bridge.governance_tools import register_governance_tools
    from tools.gimo_server.mcp_bridge.mcp_app_dashboard import register_dashboard_app
    register_native_tools(mcp)
    register_governance_tools(mcp)
    register_dashboard_app(mcp)


async def _startup_and_run() -> None:
    settings = get_settings()
    # Ensure dirs
    settings.ops_data_dir.mkdir(parents=True, exist_ok=True)
    for d in ["drafts", "approved", "runs", "threads"]:
        (settings.ops_data_dir / d).mkdir(parents=True, exist_ok=True)

    # Auto-start GIMO HTTP backend so dynamic tools work immediately
    _auto_start_backend()

    _register_dynamic()
    _register_native()

    await mcp.run_stdio_async()


def main():
    asyncio.run(_startup_and_run())


if __name__ == "__main__":
    main()
