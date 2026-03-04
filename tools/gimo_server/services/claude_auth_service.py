import asyncio
import logging
from typing import Dict, Any

logger = logging.getLogger("orchestrator.services.claude_auth")


class ClaudeAuthService:
    """Gestiona la autenticacion nativa para Claude CLI."""
    @classmethod
    async def start_login_flow(cls) -> Dict[str, Any]:
        """
        Inicia el proceso de login de claude. Este comando típicamente
        abre el navegador web predeterminado del sistema operativo local.
        """
        try:
            # Nota: 'claude login' abre el navegador y espera el callback.
            process = await asyncio.create_subprocess_exec(
                "claude",
                "login",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            logger.warning("Claude CLI not found. Simulating login flow for development.")
            return {
                "status": "pending",
                "message": "Claude CLI no está instalada o no está en el PATH.",
                "poll_id": "mock_poll_id"
            }

        # Lanzamos la tarea de fondo para esperar a que termine el comando
        # vaciando el buffer de salida para evitar bloqueos del SO.
        asyncio.create_task(cls._wait_for_login(process))

        return {
            "status": "pending",
            "message": "Se ha abierto una pestaña en tu navegador. Por favor completa el login allí.",
            "poll_id": "real_poll_id"
        }

    @classmethod
    async def _wait_for_login(cls, process: asyncio.subprocess.Process):
        """Espera a que termine el comando de claude."""
        try:
            # Consumimos la salida para que no se bloquee la pipe
            stdout_data, _ = await process.communicate()
            if process.returncode == 0:
                logger.info(f"Claude CLI login completado con éxito. Salida: {stdout_data.decode(errors='ignore').strip()}")
            else:
                logger.error(f"Claude CLI login falló con código {process.returncode}. Salida: {stdout_data.decode(errors='ignore').strip()}")
        except Exception as e:
            logger.error(f"Error esperando a que claude login terminara: {e}")
