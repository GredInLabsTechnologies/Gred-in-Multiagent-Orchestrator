"""Codex CLI authentication service.

Uses subprocess.Popen (sync) via run_in_executor so that it works under
uvicorn's SelectorEventLoop on Windows, which does not support
asyncio.create_subprocess_*.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import sys
import threading
from typing import Any, Dict

logger = logging.getLogger("orchestrator.services.codex_auth")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_URL_RE = re.compile(r"https?://\S+")
_CODE_RE = re.compile(r"\b([A-Z0-9]{3,6}-[A-Z0-9]{3,6})\b")


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


def _device_flow_sync(binary: str) -> Dict[str, Any]:
    """Blocking: start 'codex login --device-auth' and read until URL+code found."""
    try:
        proc = _popen(
            [binary, "login", "--device-auth"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        logger.error("[codex-login] failed to spawn: %s", detail, exc_info=True)
        return {
            "status": "error",
            "message": f"No se pudo iniciar Codex CLI: {detail}",
            "action": "npm install -g @openai/codex",
        }

    logger.info("[codex-login] process started, pid=%s", proc.pid)

    verification_url: str | None = None
    user_code: str | None = None
    all_lines: list[str] = []

    try:
        # readline() blocks; we rely on the thread timeout from asyncio.wait_for
        assert proc.stdout is not None
        while True:
            raw = proc.stdout.readline()
            if not raw:
                logger.info("[codex-login] stdout EOF")
                break
            decoded = raw.decode(errors="replace").strip()
            clean = _ANSI_RE.sub("", decoded)
            if clean:
                all_lines.append(clean)
                logger.info("[codex-login] stdout> %s", clean)

            if not verification_url:
                m = _URL_RE.search(clean)
                if m:
                    verification_url = m.group(0)

            if not user_code:
                m2 = _CODE_RE.search(clean)
                if m2:
                    user_code = m2.group(1)

            if verification_url and user_code:
                break
    except Exception as exc:
        logger.error("[codex-login] read error: %s", exc, exc_info=True)
        try:
            proc.kill()
        except Exception:
            pass
        return {
            "status": "error",
            "message": f"Error leyendo salida de Codex CLI: {exc}",
            "action": None,
        }

    logger.info(
        "[codex-login] parsed url=%s code=%s (lines=%d)",
        verification_url, user_code, len(all_lines),
    )

    if not verification_url or not user_code:
        full_output = " | ".join(all_lines[:8])
        logger.error("[codex-login] could not parse URL/code. Output:\n%s", "\n".join(all_lines))
        try:
            proc.kill()
        except Exception:
            pass
        lower = full_output.lower()
        if "429" in full_output or "too many requests" in lower:
            return {
                "status": "error",
                "message": "Rate limit de OpenAI (429). Espera 1-2 minutos antes de reintentar.",
                "action": None,
            }
        if "device code" in lower and "disabled" in lower:
            return {
                "status": "error",
                "message": "Autorización por código de dispositivo desactivada. Actívala en chatgpt.com → Security Settings.",
                "action": None,
            }
        if "error" in lower:
            return {
                "status": "error",
                "message": f"Codex CLI error: {full_output[:200]}",
                "action": "Actualiza Codex CLI: npm install -g @openai/codex",
            }
        return {
            "status": "error",
            "message": "No se pudo extraer verification_url/user_code de Codex CLI",
            "detail": full_output[:200],
            "action": "Actualiza o reinstala Codex CLI: npm install -g @openai/codex",
        }

    # Keep the process alive in a daemon thread so it completes the auth handshake
    def _wait():
        rc = proc.wait()
        if rc == 0:
            logger.info("[codex-login] device auth completed successfully")
        else:
            logger.error("[codex-login] device auth exited with code %s", rc)

    threading.Thread(target=_wait, daemon=True, name="codex-login-wait").start()

    return {
        "status": "pending",
        "verification_url": verification_url,
        "user_code": user_code,
        "message": "Please open the URL and enter the code to authenticate.",
        "poll_id": "real_poll_id",
    }


class CodexAuthService:
    """Gestiona la autenticacion Device Code Flow para Codex."""

    @classmethod
    async def start_device_flow(cls) -> Dict[str, Any]:
        binary = "codex"
        which_result = shutil.which(binary)
        logger.info("[codex-login] shutil.which('%s') = %s", binary, which_result)

        if which_result is None:
            logger.error("[codex-login] binary not found in PATH")
            return {
                "status": "error",
                "message": "Codex CLI no detectado",
                "action": "npm install -g @openai/codex",
            }

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _device_flow_sync, binary),
                timeout=20.0,
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.error("[codex-login] overall timeout (20s)")
            return {
                "status": "error",
                "message": "Timeout esperando instrucciones de login de Codex CLI",
                "action": "Reintenta el login o reinstala Codex CLI: npm install -g @openai/codex",
            }
        return result

    @classmethod
    async def get_auth_status(cls) -> Dict[str, Any]:
        """Check authentication via 'codex login status' (sync in executor)."""
        if shutil.which("codex") is None:
            return {"authenticated": False, "method": None, "detail": "Codex CLI not installed"}

        loop = asyncio.get_event_loop()
        try:
            rc, output = await asyncio.wait_for(
                loop.run_in_executor(None, _run, ["codex", "login", "status"]),
                timeout=10.0,
            )
        except (asyncio.TimeoutError, TimeoutError):
            return {"authenticated": False, "method": None, "detail": "timeout"}
        except Exception as exc:
            logger.error("[codex-status] error: %s", exc)
            return {"authenticated": False, "method": None, "detail": str(exc)}

        logger.info("[codex-status] rc=%s output=%r", rc, output[:120])

        if output:
            authenticated = rc == 0 and "logged in" in output.lower()
        else:
            authenticated = rc == 0

        method = None
        if "chatgpt" in output.lower():
            method = "ChatGPT"
        elif "api key" in output.lower():
            method = "API Key"

        return {
            "authenticated": authenticated,
            "method": method,
            "detail": output or ("Authenticated (rc=0)" if authenticated else ""),
        }

    @classmethod
    async def logout(cls) -> Dict[str, Any]:
        """Log out from codex CLI via 'codex logout' (sync in executor)."""
        if shutil.which("codex") is None:
            return {"status": "error", "message": "Codex CLI not installed"}

        loop = asyncio.get_event_loop()
        try:
            rc, output = await asyncio.wait_for(
                loop.run_in_executor(None, _run, ["codex", "logout"]),
                timeout=10.0,
            )
        except (asyncio.TimeoutError, TimeoutError):
            return {"status": "error", "message": "Timeout al cerrar sesión de Codex"}
        except Exception as exc:
            logger.error("[codex-logout] error: %s", exc)
            return {"status": "error", "message": str(exc)}

        logger.info("[codex-logout] rc=%s output=%s", rc, output)
        return {"status": "ok", "message": output or "Sesión de Codex cerrada"}
