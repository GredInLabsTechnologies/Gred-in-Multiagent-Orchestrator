from mcp.server.fastmcp import FastMCP
import logging
import time
import sys
import re
from typing import Any
from tools.gimo_server.services.sub_agent_manager import SubAgentManager
from tools.gimo_server.services.system_service import SystemService

# Global state for hot-reloading
_server_start_time = time.time()
_active_run_worker = None

# Initialize FastMCP server
mcp = FastMCP("GIMO", dependencies=["httpx", "uvicorn", "fastapi"])

# Configure logging
logger = logging.getLogger("mcp_server")

@mcp.tool()
async def gimo_get_status() -> str:
    """Returns the current health status and basic system info of GIMO Engine."""
    try:
        from tools.gimo_server.services.provider_catalog_service import ProviderCatalogService
        ollama_ok = await ProviderCatalogService._ollama_health()
        
        # Check backend port
        import socket
        backend_running = False
        try:
            with socket.create_connection(("127.0.0.1", 9325), timeout=0.5):
                backend_running = True
        except:
            pass
            
        status = "RUNNING" if (ollama_ok or backend_running) else "STOPPED"
        details = []
        details.append(f"Engine: {status}")
        details.append(f"Ollama: {'CONNECTED' if ollama_ok else 'OFFLINE'}")
        details.append(f"Backend-API: {'UP' if backend_running else 'DOWN'}")
        
        return "\n".join(details)
    except Exception as e:
        logger.error(f"gimo_get_status failed: {e}")
        return f"Error checking GIMO status: {e}"

@mcp.tool()
async def gimo_wake_ollama() -> str:
    """Attempts to start the local Ollama service if it is offline."""
    from tools.gimo_server.services.provider_catalog_service import ProviderCatalogService
    
    logger.info("Manual wake-up for Ollama triggered via MCP.")
    success = await ProviderCatalogService.ensure_ollama_ready()
    
    if success:
        return "Ollama service is now ONLINE and ready."
    else:
        return "Failed to wake up Ollama. Check if it is installed and available in PATH."

@mcp.tool()
def gimo_start_engine() -> str:
    """
    Starts the GIMO backend (uvicorn on port 9325) and frontend (vite on port 5173)
    if they are not already running. Processes are bound to 127.0.0.1 for security.
    This tool is LOCAL_ONLY and must not be exposed to external channels.
    """
    import socket
    import subprocess
    import sys
    from pathlib import Path

    def _is_port_open(port: int) -> bool:
        """Try connecting to localhost:port. Returns True if something is listening."""
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            return False

    # Root discovery relative to this file
    root = Path(__file__).resolve().parents[2]
    report = []

    # --- Backend (uvicorn) ---
    if _is_port_open(9325):
        report.append("✅ Backend: already running on 127.0.0.1:9325")
    else:
        try:
            subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn",
                    "tools.gimo_server.main:app",
                    "--host", "127.0.0.1",
                    "--port", "9325",
                    "--log-level", "info",
                ],
                cwd=str(root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            report.append("🚀 Backend: spawned uvicorn on 127.0.0.1:9325")
        except Exception as e:
            report.append(f"❌ Backend: failed to start — {e}")

    # --- Frontend (vite) ---
    frontend_dir = root / "tools" / "orchestrator_ui"
    if _is_port_open(5173):
        report.append("✅ Frontend: already running on 127.0.0.1:5173")
    elif not frontend_dir.exists():
        report.append(f"⚠ Frontend: directory not found at {frontend_dir}")
    else:
        try:
            subprocess.Popen(
                ["npm", "run", "dev", "--", "--host", "127.0.0.1"],
                cwd=str(frontend_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                shell=True,
            )
            report.append("🚀 Frontend: spawned vite on 127.0.0.1:5173")
        except Exception as e:
            report.append(f"❌ Frontend: failed to start — {e}")

    report.append("")
    report.append("Open: http://127.0.0.1:5173 (allow ~5s for processes to boot)")
    return "\n".join(report)


@mcp.tool()
def gimo_get_server_info() -> str:
    """
    Returns GIMO MCP server diagnostics: startup time, code file modification timestamps
    and hashes for key modules. Use this to detect stale/cached code.
    """
    import hashlib
    import importlib
    from pathlib import Path
    from datetime import datetime, timezone

    uptime_s = int(time.time() - _server_start_time)
    started_at = datetime.fromtimestamp(_server_start_time, tz=timezone.utc).isoformat()

    # Key modules to track for staleness
    module_keys = [
        "tools.gimo_server.services.run_worker",
        "tools.gimo_server.mcp_server",
        "tools.gimo_server.services.provider_service",
    ]

    lines = [
        "GIMO MCP Server Diagnostics",
        f"Started : {started_at}",
        f"Uptime  : {uptime_s}s",
        f"Worker  : {'running' if _active_run_worker else 'not started'}",
        f"sys.exe : {sys.executable}",
        f"sys.path: {sys.path[:3]}...",
        "",
        "Module File States (mtime vs import cache):",
    ]

    for mod_name in module_keys:
        try:
            mod = importlib.import_module(mod_name)
            src_file = getattr(mod, "__file__", None)
            if src_file:
                p = Path(src_file).resolve()
                disk_mtime = p.stat().st_mtime
                disk_hash = hashlib.md5(p.read_bytes()).hexdigest()[:8]
                mod_mtime = getattr(mod, "_cached_mtime", None)
                stale = "⚠ STALE" if (mod_mtime and mod_mtime != disk_mtime) else "✅ current"
                lines.append(f"  {mod_name.split('.')[-1]}: {p}")
                lines.append(f"    mtime={int(disk_mtime)} hash={disk_hash} [{stale}]")
            else:
                lines.append(f"  {mod_name.split('.')[-1]}: no source file")
        except Exception as e:
            lines.append(f"  {mod_name.split('.')[-1]}: error → {e}")

    lines.append("")
    lines.append("Tip: Run gimo_reload_worker() if run_worker shows as STALE.")
    return "\n".join(lines)


@mcp.tool()
async def gimo_reload_worker() -> str:
    """
    Hot-reloads the RunWorker module without restarting the MCP server process.
    Use this after editing run_worker.py to pick up changes immediately.
    """
    global _active_run_worker
    import importlib
    import sys

    steps = []

    # 1. Stop existing worker
    if _active_run_worker is not None:
        try:
            await _active_run_worker.stop()
            steps.append("✅ Old RunWorker stopped")
        except Exception as e:
            steps.append(f"⚠ Could not stop old worker cleanly: {e}")
        _active_run_worker = None

    # 2. Force-reload the module from disk
    try:
        mod_name = "tools.gimo_server.services.run_worker"
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            importlib.reload(mod)
            steps.append(f"✅ Module '{mod_name}' reloaded from disk")
        else:
            importlib.import_module(mod_name)
            steps.append(f"✅ Module '{mod_name}' freshly imported")
    except Exception as e:
        steps.append(f"❌ Module reload failed: {e}")
        return "\n".join(steps)

    # 3. Also reload any sub-dependencies cached in sys.modules that may have changed
    for sub in ["tools.gimo_server.services.file_service"]:
        if sub in sys.modules:
            try:
                importlib.reload(sys.modules[sub])
                steps.append(f"✅ Reloaded sub-module: {sub.split('.')[-1]}")
            except Exception as e:
                steps.append(f"⚠ Could not reload {sub}: {e}")

    # 4. Instantiate and start fresh worker
    try:
        from tools.gimo_server.services.run_worker import RunWorker
        _active_run_worker = RunWorker()
        await _active_run_worker.start()
        steps.append("✅ New RunWorker instantiated and started")
    except Exception as e:
        steps.append(f"❌ Failed to start new worker: {e}")
        return "\n".join(steps)

    steps.append("")
    steps.append("🚀 GIMO RunWorker hot-reloaded successfully. Code changes are now live.")
    return "\n".join(steps)

@mcp.tool()
async def gimo_list_agents() -> str:
    """Lists all available sub-agents and their descriptions currently registered in GIMO."""
    try:
        # Trigger dynamic sync before listing
        await SubAgentManager.sync_with_ollama()
        
        agents = SubAgentManager.get_sub_agents()
        if not agents:
            return "No agents found in GIMO."
        
        lines = ["Available GIMO Agents:"]
        for ag in agents:
            lines.append(f"- ID: {ag.id} | Name: {ag.name} | Description: {ag.description}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing agents: {e}"

def _generate_mermaid_graph(plan_data: Any) -> str:
    """Helper to generate a Mermaid graph from OpsPlan data."""
    try:
        from tools.gimo_server.ops_models import OpsPlan
        if isinstance(plan_data, str):
            import json
            plan_data = json.loads(plan_data)
        
        # If it's a dict, try to validate it
        if isinstance(plan_data, dict):
            plan = OpsPlan.model_validate(plan_data)
        else:
            plan = plan_data

        lines = ["graph TD"]
        for task in plan.tasks:
            node_id = task.id.replace("-", "_")
            label = f"\"{task.title}<br/>[{task.status}]\""
            lines.append(f"    {node_id}[{label}]")
            for dep in task.depends:
                dep_id = dep.replace("-", "_")
                lines.append(f"    {dep_id} --> {node_id}")
        
        return "\n".join(lines)
    except Exception as e:
        return f"Error al generar grafo: {e}"

@mcp.tool()
async def gimo_propose_structured_plan(task_instructions: str) -> str:
    """
    Generates a structured multi-step plan with task dependencies, system prompts per agent, and Mermaid graph.
    """
    try:
        from tools.gimo_server.services.ops_service import OpsService
        from tools.gimo_server.services.provider_service import ProviderService
        from tools.gimo_server.ops_models import OpsPlan, AgentProfile
        import json
        import time
        import os

        system_prompt = (
            "You are a senior systems architect designing a MODULAR, DISRUPTIVE multi-agent execution plan.\n"
            f"Task: '{task_instructions}'\n\n"
            "=== RULES (MANDATORY) ===\n"
            "1. tasks[0] MUST be the Lead Orchestrator.\n"
            "2. Choose the best model fit.\n"
            "3. Response ONLY with valid JSON.\n"
        )

        try:
            response = await ProviderService.static_generate(
                prompt=system_prompt,
                context={"task_type": "disruptive_planning"}
            )
            raw_content = response.get("content", "").strip()
            if raw_content.startswith("```"):
                raw_content = re.sub(r"```(json)?\n?|```", "", raw_content).strip()
            plan_dict = json.loads(raw_content)
            plan_data = OpsPlan.model_validate(plan_dict)
        except Exception:
            from datetime import datetime
            plan_data = OpsPlan(
                id=f"plan_{int(time.time())}",
                title="[FALLBACK] Modular Agent Plan",
                workspace="gred_in_multiagent_orchestrator",
                created=datetime.now().isoformat(),
                objective=task_instructions,
                tasks=[],
                constraints=[]
            )

        graph = _generate_mermaid_graph(plan_data)
        draft = OpsService.create_draft(
            prompt=task_instructions,
            content=plan_data.model_dump_json(indent=2),
            context={"structured": True, "mermaid": graph},
            provider="mcp_disruptive_planner"
        )
        return f"🚀 Plan propuesto (Draft: {draft.id}):\n```mermaid\n{graph}\n```"
    except Exception as e:
        return f"Error al proponer plan: {e}"

@mcp.tool()
def gimo_get_plan_graph(draft_or_run_id: str) -> str:
    """Returns the Mermaid graph visualization for a draft or run."""
    try:
        from tools.gimo_server.services.ops_service import OpsService
        content = None
        if draft_or_run_id.startswith("r_"):
            run = OpsService.get_run(draft_or_run_id)
            if run:
                approved = OpsService.get_approved(run.approved_id)
                content = approved.content if approved else None
        else:
            draft = OpsService.get_draft(draft_or_run_id)
            content = draft.content if draft else None
        if not content: return f"No plan found for {draft_or_run_id}"
        graph = _generate_mermaid_graph(content)
        return f"```mermaid\n{graph}\n```"
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
async def gimo_create_draft(task_instructions: str, target_agent_id: str = "auto") -> str:
    try:
        from tools.gimo_server.services.ops_service import OpsService
        draft = OpsService.create_draft(prompt=task_instructions, content="Plan...", provider="mcp")
        return f"Draft: {draft.id}"
    except Exception as e: return str(e)

@mcp.tool()
def gimo_get_draft(draft_id: str) -> str:
    try:
        from tools.gimo_server.services.ops_service import OpsService
        draft = OpsService.get_draft(draft_id)
        return draft.content if draft else "Not found"
    except Exception as e: return str(e)

@mcp.tool()
def gimo_approve_draft(draft_id: str) -> str:
    try:
        from tools.gimo_server.services.ops_service import OpsService
        approved = OpsService.approve_draft(draft_id, approved_by="human")
        run = OpsService.create_run(approved.id)
        return f"Approved. Run: {run.id}"
    except Exception as e: return str(e)

@mcp.tool()
def gimo_run_task(task_instructions: str, target_agent_id: str = "auto") -> str:
    try:
        from tools.gimo_server.services.ops_service import OpsService
        draft = OpsService.create_draft(prompt=task_instructions, provider="mcp_auto")
        approved = OpsService.approve_draft(draft.id, approved_by="auto")
        run = OpsService.create_run(approved.id)
        return f"Running. Run ID: {run.id}"
    except Exception as e: return str(e)

@mcp.tool()
def gimo_get_task_status(run_id: str) -> str:
    try:
        from tools.gimo_server.services.ops_service import OpsService
        run = OpsService.get_run(run_id)
        return f"Status: {run.status}" if run else "Not found"
    except Exception as e: return str(e)

@mcp.tool()
def gimo_resolve_handover(run_id: str, decision: str, edited_state: dict = None) -> str:
    try:
        from tools.gimo_server.services.ops_service import OpsService
        OpsService.update_run_status(run_id, "running", msg=f"Resolved: {decision}")
        return "OK"
    except Exception as e: return str(e)

@mcp.tool()
async def gimo_spawn_subagent(name: str, task: str, role: str = "worker") -> str:
    try:
        from tools.gimo_server.services.sub_agent_manager import SubAgentManager
        req = {"modelPreference": "default", "constraints": {"role": role, "task": task}}
        agent = await SubAgentManager.create_sub_agent(parent_id="mcp", request=req)
        return f"Spawned: {agent.id}"
    except Exception as e: return str(e)

async def _startup_and_run() -> None:
    from tools.gimo_server.config import get_settings
    from tools.gimo_server.security.license_guard import LicenseGuard
    from tools.gimo_server.services.run_worker import RunWorker
    settings = get_settings()
    # Ensure dirs
    settings.ops_data_dir.mkdir(parents=True, exist_ok=True)
    for d in ["drafts", "approved", "runs", "threads"]:
        (settings.ops_data_dir / d).mkdir(parents=True, exist_ok=True)
    
    global _active_run_worker
    _active_run_worker = RunWorker()
    await _active_run_worker.start()
    try:
        await mcp.run_stdio_async()
    finally:
        await _active_run_worker.stop()

if __name__ == "__main__":
    import asyncio
    asyncio.run(_startup_and_run())
