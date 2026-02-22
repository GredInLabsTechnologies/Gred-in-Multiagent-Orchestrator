"""
GIMO MCP Handshake Real — Validación del Flujo Completo
=========================================================
Flujo real: MCP Client → stdio → GIMO MCP Server → Ollama → Qwen

Este script NO hace trucos: usa el protocolo MCP estándar por stdio.
El servidor GIMO arranca como subproceso separado (igual que haría un orquestador real).
"""
import asyncio
import os
import sys
import re
import logging

# Fix encoding para consola Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mcp_test_client")

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def main() -> int:
    """
    Valida el flujo MCP real completo.
    Returns 0 on success, 1 on failure.
    """
    print("\n" + "=" * 60)
    print("  GIMO MCP Real Handshake")
    print("=" * 60)

    # Entorno del servidor MCP (se pasa como subproceso)
    server_env = os.environ.copy()
    server_env["DEBUG"] = "true"
    server_env["ORCH_LICENSE_ALLOW_DEBUG_BYPASS"] = "true"
    server_env["ORCH_REPO_ROOT"] = os.environ.get(
        "ORCH_REPO_ROOT",
        r"C:\Users\shilo\Documents\Github\gimo_dummy_test",
    )
    server_env["PYTHONIOENCODING"] = "utf-8"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-m", "tools.gimo_server.mcp_server"],
        env=server_env,
    )

    print("\n[1/4] Arrancando GIMO MCP Server como subproceso...")
    print(f"      Repo root: {server_env['ORCH_REPO_ROOT']}")

    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            print("[1/4] Streams stdio abiertos. Iniciando ClientSession...")

            async with ClientSession(read_stream, write_stream) as session:

                # PASO 1: Handshake / initialize
                print("\n[2/4] Ejecutando MCP initialize (handshake)...")
                try:
                    await asyncio.wait_for(session.initialize(), timeout=20.0)
                    print("[2/4] OK — handshake MCP completado.")
                except asyncio.TimeoutError:
                    print("[2/4] FAIL — Timeout en session.initialize() (20s)")
                    print("       El servidor MCP no respondió al handshake.")
                    return 1
                except Exception as exc:
                    print(f"[2/4] FAIL — Error en initialize: {exc}")
                    return 1

                # PASO 2: Listar tools disponibles
                print("\n[3/4] Listando tools del servidor MCP...")
                try:
                    tools_result = await asyncio.wait_for(
                        session.list_tools(), timeout=10.0
                    )
                    tool_names = [t.name for t in tools_result.tools]
                    print(f"[3/4] Tools disponibles: {tool_names}")
                    if "gimo_run_task" not in tool_names:
                        print("[3/4] WARN — 'gimo_run_task' no encontrado en tools.")
                except asyncio.TimeoutError:
                    print("[3/4] FAIL — Timeout listando tools.")
                    return 1
                except Exception as exc:
                    print(f"[3/4] FAIL — Error listando tools: {exc}")
                    return 1

                # PASO 3: Invocar gimo_run_task (tarea simple para Qwen)
                task_prompt = (
                    "Responde solo con: 'Qwen worker OK via GIMO MCP'. "
                    "Nada más."
                )
                print(f"\n[4/4] Invocando gimo_run_task...")
                print(f"      Prompt: {task_prompt}")

                try:
                    response = await asyncio.wait_for(
                        session.call_tool(
                            "gimo_run_task",
                            {"task_instructions": task_prompt},
                        ),
                        timeout=30.0,
                    )
                    output = response.content[0].text
                    print(f"\n[4/4] GIMO respondio:\n      {output}")

                    # Extraer Run ID si lo hay
                    run_id_match = re.search(r"Run ID: (r_\w+)", output)
                    if run_id_match:
                        run_id = run_id_match.group(1)
                        print(f"\n      Run ID obtenido: {run_id}")

                        # Polling rápido de estado
                        print("\n      Consultando estado del run...")
                        for i in range(20):  # 40 segundos total
                            await asyncio.sleep(2)
                            try:
                                status_res = await asyncio.wait_for(
                                    session.call_tool(
                                        "gimo_get_task_status", {"run_id": run_id}
                                    ),
                                    timeout=15.0,
                                )
                                status_text = status_res.content[0].text
                                print(f"      [t+{(i+1)*2}s] {status_text.strip()}")
                                if any(
                                    kw in status_text.lower()
                                    for kw in ("done", "completed", "error", "failed")
                                ):
                                    break
                            except Exception as poll_exc:
                                print(f"      Polling error: {poll_exc}")
                                break

                except asyncio.TimeoutError:
                    print("[4/4] FAIL — Timeout en gimo_run_task (30s).")
                    return 1
                except Exception as exc:
                    print(f"[4/4] FAIL — Error en gimo_run_task: {exc}")
                    return 1

    except Exception as exc:
        print(f"\nFAIL — Error arrancando el servidor MCP: {exc}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1

    print("\n" + "=" * 60)
    print("  RESULTADO: Flujo MCP validado correctamente.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCerrado por el usuario.")
        exit_code = 130
    sys.exit(exit_code)
