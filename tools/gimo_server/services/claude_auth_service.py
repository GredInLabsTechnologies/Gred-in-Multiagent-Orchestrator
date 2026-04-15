"""Claude CLI authentication service.

Uses subprocess.Popen (sync) via run_in_executor so that it works under
uvicorn's SelectorEventLoop on Windows, which does not support
asyncio.create_subprocess_*.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
import threading
from typing import Any, Dict

logger = logging.getLogger("orchestrator.services.claude_auth")


def _popen(args: list[str], **kwargs) -> subprocess.Popen:
    """Spawn a subprocess; use shell=True on Windows for .cmd shim compat."""
    if sys.platform == "win32":
        return subprocess.Popen(" ".join(args), shell=True, **kwargs)  # nosec B602
    return subprocess.Popen(args, **kwargs)


def _run(args: list[str], timeout: float = 8) -> tuple[int, str]:
    """Run a command synchronously and return (returncode, combined_output)."""
    try:
        proc = _popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, (out or b"").decode("utf-8", errors="replace").strip()
    except subprocess.TimeoutExpired as exc:
        try:
            exc.process.kill()
        except Exception:
            pass
        raise
    except Exception:
        raise


def _login_flow_sync(binary: str) -> Dict[str, Any]:
    """Blocking: start 'claude auth login' which opens a browser tab."""
    try:
        proc = _popen(
            [binary, "auth", "login"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        logger.error("[claude-login] failed to spawn: %s", detail, exc_info=True)
        return {
            "status": "error",
            "message": f"No se pudo iniciar Claude CLI: {detail}",
            "action": "npm install -g @anthropic-ai/claude-code",
        }

    logger.info("[claude-login] process started, pid=%s", proc.pid)

    # Keep the process alive in a daemon thread so it completes the auth handshake
    def _wait():
        try:
            out, _ = proc.communicate()
            rc = proc.returncode
            if rc == 0:
                logger.info("[claude-login] auth completed successfully")
            else:
                output = (out or b"").decode("utf-8", errors="replace").strip()
                logger.error("[claude-login] auth exited with code %s. Output: %s", rc, output)
        except Exception as e:
            logger.error("[claude-login] wait error: %s", e)

    threading.Thread(target=_wait, daemon=True, name="claude-login-wait").start()

    return {
        "status": "pending",
        "message": "Se ha abierto una pestaña en tu navegador. Por favor completa el login allí.",
        "poll_id": "real_poll_id",
    }


class ClaudeAuthService:
    """Gestiona la autenticacion nativa para Claude CLI."""

    @classmethod
    async def start_login_flow(cls) -> Dict[str, Any]:
        binary = "claude"
        which_result = shutil.which(binary)
        logger.info("[claude-login] shutil.which('%s') = %s", binary, which_result)

        if which_result is None:
            logger.error("[claude-login] binary not found in PATH")
            return {
                "status": "error",
                "message": "Claude CLI no detectado",
                "action": "npm install -g @anthropic-ai/claude-code",
            }

        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _login_flow_sync, binary),
                timeout=20.0,
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.error("[claude-login] overall timeout (20s)")
            return {
                "status": "error",
                "message": "Timeout esperando inicio de sesión de Claude CLI",
                "action": "Reintenta el login o reinstala Claude CLI: npm install -g @anthropic-ai/claude-code",
            }
        return result

    @classmethod
    async def get_auth_status(cls) -> Dict[str, Any]:
        """Check if claude CLI is authenticated via `claude auth status`."""
        import json as _json
        if shutil.which("claude") is None:
            return {"authenticated": False, "method": None, "detail": "Claude CLI not installed"}

        loop = asyncio.get_running_loop()
        try:
            rc, output = await asyncio.wait_for(
                loop.run_in_executor(None, _run, ["claude", "auth", "status"]),
                timeout=10.0,
            )
        except (asyncio.TimeoutError, TimeoutError):
            return {"authenticated": False, "method": None, "detail": "timeout"}
        except Exception as exc:
            logger.error("[claude-status] error: %s", exc)
            return {"authenticated": False, "method": None, "detail": str(exc)}

        logger.info("[claude-status] rc=%s output=%r", rc, output[:120])

        # Try JSON parse first
        try:
            data = _json.loads(output)
            return {
                "authenticated": bool(data.get("loggedIn")),
                "method": data.get("authMethod"),
                "email": data.get("email"),
                "plan": data.get("subscriptionType"),
                "detail": output,
            }
        except _json.JSONDecodeError:
            pass

        authenticated = "logged in" in output.lower() or rc == 0
        return {"authenticated": authenticated, "method": None, "detail": output}

    @classmethod
    async def logout(cls) -> Dict[str, Any]:
        """Log out from claude CLI via `claude auth logout`."""
        if shutil.which("claude") is None:
            return {"status": "error", "message": "Claude CLI not installed"}

        loop = asyncio.get_running_loop()
        try:
            rc, output = await asyncio.wait_for(
                loop.run_in_executor(None, _run, ["claude", "auth", "logout"]),
                timeout=10.0,
            )
        except (asyncio.TimeoutError, TimeoutError):
            return {"status": "error", "message": "Timeout al cerrar sesión de Claude"}
        except Exception as exc:
            logger.error("[claude-logout] error: %s", exc)
            return {"status": "error", "message": str(exc)}

        logger.info("[claude-logout] rc=%s output=%s", rc, output)
        return {"status": "ok", "message": output or "Sesión de Claude cerrada"}
