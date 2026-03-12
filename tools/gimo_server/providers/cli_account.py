from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
from asyncio.subprocess import PIPE
from typing import Any, Dict, List

from .base import ProviderAdapter

logger = logging.getLogger("orchestrator.providers.cli_account")


async def _create_process(cmd: List[str], **kwargs) -> asyncio.subprocess.Process:
    """Create subprocess, using shell on Windows for npm .cmd shim compat."""
    if sys.platform == "win32":
        return await asyncio.create_subprocess_shell(" ".join(cmd), **kwargs)
    return await asyncio.create_subprocess_exec(*cmd, **kwargs)


def _parse_codex_jsonl(raw: str) -> str:
    """Extract assistant message content from Codex JSONL (--json) output.

    Each line is a JSON object. We look for message events with role=assistant
    and concatenate their text content.
    """
    parts: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Codex JSONL emits various event types. Extract text from message events.
        if isinstance(event, dict):
            # Format: {"type": "message", "role": "assistant", "content": [{"type":"output_text","text":"..."}]}
            if event.get("role") == "assistant":
                for part in event.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        parts.append(part.get("text", ""))
            # Also handle direct text events
            elif event.get("type") == "output_text":
                parts.append(event.get("text", ""))
    return "\n".join(parts).strip() if parts else raw


class CliAccountAdapter(ProviderAdapter):
    """ProviderAdapter for account-mode CLI providers (Codex/Claude).

    This adapter does not require API keys and relies on a user-authenticated
    local CLI session.
    """

    def __init__(self, *, binary: str):
        self.binary = str(binary or "").strip()
        # Detect CLI type from binary name
        self._is_claude = "claude" in self.binary.lower()
        self._is_codex = "codex" in self.binary.lower()

    def _build_cmd(self, prompt: str) -> List[str]:
        """Build the correct command for this CLI binary."""
        if self._is_claude:
            # claude -p "<prompt>"  (print/non-interactive mode)
            return [self.binary, "-p", str(prompt)]
        else:
            # codex exec "<prompt>" --json  (JSONL output)
            return [self.binary, "exec", str(prompt), "--json"]

    def _build_env(self) -> dict:
        """Build environment for subprocess, clearing nested-session guards."""
        import os
        env = {**os.environ, "PYTHONUTF8": "1"}
        if self._is_claude:
            # Claude Code refuses to run inside another Claude Code session.
            # Clear the guard so it works as a provider subprocess.
            env.pop("CLAUDECODE", None)
            env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        return env

    async def generate(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if not self.binary:
            raise RuntimeError("CLI binary is not configured")
        if shutil.which(self.binary) is None:
            raise RuntimeError(f"CLI binary not found: {self.binary}")

        cmd = self._build_cmd(prompt)
        env = self._build_env()
        logger.info("[cli-account] running: %s", " ".join(cmd))

        if sys.platform == "win32":
            proc = await asyncio.create_subprocess_shell(
                " ".join(cmd), stdout=PIPE, stderr=PIPE, env=env
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=PIPE, stderr=PIPE, env=env
            )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        out = (stdout or b"").decode("utf-8", errors="ignore").strip()
        err = (stderr or b"").decode("utf-8", errors="ignore").strip()
        if proc.returncode != 0:
            logger.error("[cli-account] exit code %s, stderr: %s", proc.returncode, err[:500])
            raise RuntimeError(err or f"{self.binary} exited with code {proc.returncode}")

        if self._is_codex:
            content = _parse_codex_jsonl(out) if out else (err or "")
        else:
            # Claude -p outputs plain text directly
            content = out or err or ""

        logger.info("[cli-account] response length: %d chars", len(content))
        return {
            "content": content,
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    async def health_check(self) -> bool:
        if not self.binary or shutil.which(self.binary) is None:
            return False
        try:
            proc = await _create_process([self.binary, "--version"], stdout=PIPE, stderr=PIPE)
            await asyncio.wait_for(proc.communicate(), timeout=8)
            return proc.returncode == 0
        except Exception:
            return False
