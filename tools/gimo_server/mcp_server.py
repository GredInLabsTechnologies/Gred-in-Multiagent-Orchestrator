import asyncio
from mcp.server.fastmcp import FastMCP
from typing import Dict, List, Any

# We load GIMO's config and services
from tools.gimo_server.services.system_service import SystemService
from tools.gimo_server.services.sub_agent_manager import SubAgentManager
from tools.gimo_server.services.ops_service import OpsService

# Initialize FastMCP Server
mcp = FastMCP("GIMO Orchestrator")

@mcp.tool()
def gimo_get_status() -> str:
    """Returns the current health status and basic system info of GIMO Engine."""
    try:
        status = SystemService.get_status("GILOrchestrator")
        return f"GIMO Engine Status:\n{status}"
    except Exception as e:
        return f"Error getting GIMO status: {e}"

@mcp.tool()
def gimo_list_agents() -> str:
    """Lists all available sub-agents and their descriptions currently registered in GIMO."""
    try:
        agents = SubAgentManager.get_sub_agents()
        if not agents:
            return "No agents found in GIMO."
        
        lines = ["Available GIMO Agents:"]
        for ag in agents:
            lines.append(f"- ID: {ag.id} | Name: {ag.name} | Description: {ag.description}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing agents: {e}"

@mcp.tool()
def gimo_run_task(task_instructions: str, target_agent_id: str = "auto") -> str:
    """
    Submits a task to the GIMO engine for execution.
    
    Args:
        task_instructions: Detailed prompt or task description to be executed.
        target_agent_id: The specific sub-agent ID to route the task to, or 'auto' to let GIMO decide.
    """
    try:
        from tools.gimo_server.services.ops_service import OpsService
        
        # Creating a realistic draft request
        draft = OpsService.create_draft(
            prompt=task_instructions,
            context={"target": target_agent_id if target_agent_id != "auto" else None},
            provider="mcp_client"
        )
        
        # Approving the draft
        approved = OpsService.approve_draft(draft.id, approved_by="mcp_client")
        
        # Generate the actual runnable task
        run = OpsService.create_run(approved.id)
        
        return f"¡Tarea enviada exitosamente a GIMO! Run ID: {run.id}\nUsa 'gimo_get_task_status' con este Run ID para verificar el progreso o los resultados."
    except Exception as e:
        return f"Fallo al ejecutar la tarea en GIMO: {e}"

@mcp.tool()
def gimo_get_task_status(run_id: str) -> str:
    """
    Retrieves the execution status and final result or logs of a specific GIMO task run.
    
    Args:
        run_id: The unique run identifier returned by 'gimo_run_task'.
    """
    try:
        from tools.gimo_server.services.ops_service import OpsService
        run = OpsService.get_run(run_id)
        if not run:
            return f"Run ID {run_id} no encontrado."
            
        status_info = [
            f"Run ID: {run.id}",
            f"Estado: {run.status}",
        ]
        
        if run.error:
            status_info.append(f"Error: {run.error}")
        if hasattr(run, 'result') and run.result:
            status_info.append(f"Resultado: {run.result}")
            
        return "\n".join(status_info)
    except Exception as e:
        return f"Error al consultar el estado de la tarea: {e}"

@mcp.tool()
def gimo_resolve_handover(run_id: str, decision: str, edited_state: dict = None) -> str:
    """
    Resolves a pending human review or agent doubt returning control to GIMO.
    
    Args:
        run_id: The ID of the run/workflow that is paused.
        decision: The action to take ('approve', 'reject', 'edit', 'takeover').
        edited_state: Optional dict with state patches if decision is 'edit'.
    """
    try:
        from tools.gimo_server.services.ops_service import OpsService
        
        status_map = {
            "approve": "running",
            "reject": "aborted",
            "edit": "running",
            "takeover": "aborted"
        }
        new_status = status_map.get(decision.lower(), "pending")
        
        msg = f"Handover resuelto vía MCP: {decision}"
        if edited_state:
            msg += " | Estado inicial sobreescrito por el orquestador."
            
        OpsService.update_run_status(run_id, new_status, msg=msg)
        
        return f"Bloqueo superado para el Run {run_id}. Decisión: {decision}. GIMO continuará."
    except Exception as e:
        return f"Error al resolver handover: {e}"

@mcp.tool()
async def gimo_spawn_subagent(name: str, task: str, role: str = "worker") -> str:
    """
    Dynamically spawns a temporary sub-agent inside GIMO to handle a specific delegation.
    
    Args:
        name: Name of the temporary sub-agent.
        task: Context or goal for this specific mini-agent.
        role: Functional role (e.g. 'worker', 'reviewer', 'researcher').
    """
    try:
        from tools.gimo_server.services.sub_agent_manager import SubAgentManager
        
        # Envolviendo las constraints en un diccionario según firma 
        request = {
            "modelPreference": "default",
            "constraints": {"role": role, "task": task}
        }
        
        agent = await SubAgentManager.create_sub_agent(parent_id="mcp_coordinator", request=request)
        
        return f"SubAgent '{name}' (ID: {agent.id}) spawn completado con rol '{role}'. Objetivo asignado: {task}. Ya está encolado en GIMO."
    except Exception as e:
        return f"Fallo al desplegar el sub-agente: {e}"

if __name__ == "__main__":
    import sys
    import logging
    # Ensure BASE_DIR and environment variables are loaded
    from tools.gimo_server.config import get_settings
    settings = get_settings()
    
    # CRITICAL: MCP over stdio requires stdout for JSON only. All logs must go to stderr.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    logger = logging.getLogger("mcp")
    logger.info("Starting GIMO FastMCP Server (Stdout is reserved for JSON-RPC)...")
    
    # We must start the license guard and DBs if we need the full engine
    from tools.gimo_server.security.license_guard import LicenseGuard
    import asyncio
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    guard = LicenseGuard(settings)
    status = loop.run_until_complete(guard.validate())
    
    if not status.valid:
        logger.error(f"License invalid: {status.reason}")
        sys.exit(1)
        
    try:
        from tools.gimo_server.services.provider_service import ProviderService
        ProviderService.ensure_default_config()
    except Exception as e:
        logger.warning(f"Provider config check warning: {e}")
        
    mcp.run()
