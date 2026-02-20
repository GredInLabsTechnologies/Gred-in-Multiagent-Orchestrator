import asyncio
import os
import sys
import re

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.types import CreateMessageRequestParams

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

async def main():
    print("🚀 [Antigravity Orchestrator] Lanzando GIMO MCP Server (Modo StdIO: C:\gimo_test_repo)...")
    
    # We set up the environment required for GIMO
    server_env = os.environ.copy()
    server_env["ORCH_REPO_ROOT"] = "C:\\gimo_test_repo"
    server_env["DEBUG"] = "true"
    
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "tools.gimo_server.mcp_server"],
        env=server_env
    )
    
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("✅ Conectado y Autenticado (StdIO)")
            
            async def handle_sample(request: CreateMessageRequestParams) -> str:
                print("\n🚨 [MCP SAMPLING PUSH] GIMO necesita mi intervención!")
                for msg in request.messages:
                    if msg.content.type == "text":
                        print(f"📥 {msg.content.text}")

                return {
                    "role": "assistant",
                    "content": {
                        "type": "text", 
                        "text": "approve"
                    },
                    "model": "Antigravity/Simulator",
                    "stopReason": "stop"
                }
            
            session.sampling_handler = handle_sample
            
            # Action: Creating the task
            task_prompt = "Crea un archivo python llamado 'hello_world.py' en la raiz, cuyo contenido sea imprimir 'Prueba Real completada por Ollama y GIMO'. Después ejecútalo o verifícalo."
            print(f"\n[Antigravity] Enviando tarea a GIMO Worker (Ollama):\n> {task_prompt}")
            
            response = await session.call_tool("gimo_run_task", {"task_instructions": task_prompt})
            output = response.content[0].text
            print(f"\nGIMO Responde: {output}")
            
            # Extract Run ID
            run_id_match = re.search(r'Run ID: (r_\S+)', output)
            if not run_id_match:
                print("❌ No se encontró Run ID.")
                return
            
            run_id = run_id_match.group(1)
            
            # Polling for resolution
            print(f"\n[Antigravity] Monitoreando remotamente el Run {run_id}...")
            previous_status = ""
            for i in range(120): # max 120 secs 
                await asyncio.sleep(2)
                
                try:
                    status_res = await session.call_tool("gimo_get_task_status", {"run_id": run_id})
                    current_status = status_res.content[0].text
                    
                    if current_status != previous_status:
                        print(f"\n[Update {i}s] {current_status}")
                        previous_status = current_status
                        
                    if "Estado: completed" in current_status or "Status: completed" in current_status or "Resultado:" in current_status:
                        print("\n✅ Tarea Completada con Éxito.")
                        break
                    elif "Estado: failed" in current_status or "Estado: error" in current_status:
                        print("\n❌ La tarea falló.")
                        break
                        
                except Exception as e:
                    print(f"Polling error: {e}")
            
            print("\n🏁 Finalizado.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCerrado por el usuario.")
    except Exception as e:
        import traceback
        if isinstance(e, BaseExceptionGroup):
            print("\n❌ Exception Group:")
            for exc in e.exceptions:
                traceback.print_exception(type(exc), exc, exc.__traceback__)
        else:
            traceback.print_exc()
        print(f"\n❌ Error General: {e}")
