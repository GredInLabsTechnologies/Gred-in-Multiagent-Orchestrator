import asyncio
import logging
import os
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


# ── OpenAPI-derived tool naming ───────────────────────────────────────────


def _build_name_map(spec: dict) -> dict[str, str]:
    """Derive gimo_* tool names from OpenAPI operationIds.

    Naming rule: extract meaningful path segments from the endpoint path,
    join with underscores, and prefix with ``gimo_``.  When two routes
    produce the same name (e.g. GET and POST on the same path), the HTTP
    method is appended as a suffix.
    """
    names: dict[str, str] = {}
    used: dict[str, str] = {}  # candidate → first operationId that claimed it

    for path, methods in spec.get("paths", {}).items():
        if not path.startswith("/ops/"):
            continue
        for method, details in methods.items():
            if method not in ("get", "post", "put", "delete", "patch"):
                continue
            op_id = details.get("operationId")
            if not op_id:
                continue

            segments = [
                s.replace("-", "_")
                for s in path.split("/")
                if s and s != "ops" and not s.startswith("{")
            ]
            candidate = "gimo_" + "_".join(segments)

            if candidate in used:
                # Rename both: prior owner gets its method appended too
                prior_op = used[candidate]
                if prior_op in names and names[prior_op] == candidate:
                    # Find the prior method
                    for p2, m2s in spec.get("paths", {}).items():
                        for m2, d2 in m2s.items():
                            if d2.get("operationId") == prior_op:
                                names[prior_op] = f"{candidate}_{m2}"
                                break
                candidate = f"{candidate}_{method}"

            used[candidate] = op_id
            names[op_id] = candidate

    return names


# ── Registration ──────────────────────────────────────────────────────────


def _register_dynamic():
    """Register MCP tools derived from the FastAPI OpenAPI spec at runtime.

    Uses FastMCP's OpenAPIProvider so that tool definitions are always in
    sync with the actual HTTP endpoints — zero drift by construction.
    """
    import httpx
    from fastmcp.server.providers.openapi import OpenAPIProvider

    # Import the FastAPI app purely for its OpenAPI spec (no server started).
    from tools.gimo_server.main import app as fastapi_app

    spec = fastapi_app.openapi()

    # Build the httpx client that OpenAPIProvider will use for every call.
    from tools.gimo_server.mcp_bridge.bridge import _get_auth_token
    headers: dict[str, str] = {}
    token = _get_auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    workspace = os.environ.get("ORCH_REPO_ROOT", "")
    if workspace:
        headers["X-Gimo-Workspace"] = workspace

    client = httpx.AsyncClient(
        base_url="http://127.0.0.1:9325",
        headers=headers,
        timeout=30.0,
    )

    mcp_names = _build_name_map(spec)

    def _ops_only(route, mcp_type):
        """Only expose /ops/* routes as MCP tools."""
        if not route.path.startswith("/ops/"):
            return None
        return mcp_type

    provider = OpenAPIProvider(
        spec,
        client=client,
        mcp_names=mcp_names,
        route_map_fn=_ops_only,
        validate_output=False,  # Permissive — backend already validates
    )
    mcp.add_provider(provider)

    # Static aliases with curated signatures (kept for backward compat)
    _register_static_aliases()

    logger.info(
        "OpenAPIProvider registered %d tools from OpenAPI spec (+ static aliases).",
        len(mcp_names),
    )


def _register_static_aliases():
    """Register hand-crafted tool aliases with ergonomic signatures."""
    from tools.gimo_server.mcp_bridge.bridge import proxy_to_api

    async def plan_create(
        objective: str,
        acceptance_criteria: list,
        intent_class: str,
        prompt: str | None = None,
    ) -> str:
        """Create a structured execution draft from objective + acceptance criteria."""
        body = {
            "objective": objective,
            "acceptance_criteria": acceptance_criteria,
            "execution": {"intent_class": intent_class},
        }
        if prompt is not None:
            body["prompt"] = prompt
        return await proxy_to_api("POST", "/ops/drafts", __body=body)

    async def plan_execute(draft_id: str, auto_run: bool = True) -> str:
        """Approve a draft and optionally trigger auto-run."""
        return await proxy_to_api(
            "POST",
            "/ops/drafts/{draft_id}/approve",
            __path_params={"draft_id": draft_id},
            __query={"auto_run": auto_run},
        )

    async def cost_estimate(nodes: list | None = None, initial_state: dict | None = None) -> str:
        """Estimate workflow cost using the mastery predictor endpoint."""
        return await proxy_to_api(
            "POST",
            "/ops/mastery/predict",
            __body={
                "nodes": nodes or [],
                "initial_state": initial_state or {},
            },
        )

    for alias in (plan_create, plan_execute, cost_estimate):
        try:
            mcp.add_tool(alias)
        except Exception as e:
            logger.error("Failed to register MCP alias %s: %s", alias.__name__, e)


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

    try:
        _register_dynamic()
    except Exception as exc:
        logger.error("Failed to register dynamic MCP tools: %s", exc)

    try:
        _register_native()
    except Exception as exc:
        logger.error("Failed to register native MCP tools: %s", exc)

    # Resources and prompts
    try:
        from tools.gimo_server.mcp_bridge.resources import register_resources
        register_resources(mcp)
    except Exception as exc:
        logger.error("Failed to register MCP resources: %s", exc)

    try:
        from tools.gimo_server.mcp_bridge.prompts import register_prompts
        register_prompts(mcp)
    except Exception as exc:
        logger.error("Failed to register MCP prompts: %s", exc)

    await mcp.run_stdio_async()


def main():
    asyncio.run(_startup_and_run())


if __name__ == "__main__":
    main()
