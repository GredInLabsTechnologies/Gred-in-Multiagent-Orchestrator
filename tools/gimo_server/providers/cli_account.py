from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sys
from asyncio.subprocess import PIPE
from typing import Any, Dict, List, Tuple

from .base import ProviderAdapter

logger = logging.getLogger("orchestrator.providers.cli_account")

# ── P2: CLI Tool-Calling Engine ───────────────────────────────────────────────

TOOL_CALLING_SYSTEM_PROMPT = """
IMPORTANT: When you need to use tools, respond with a JSON block in this EXACT format:

```json
{{"tool_calls": [{{"name": "tool_name", "arguments": {{"arg1": "value1"}}}}]}}
```

Then STOP and wait for [Tool Result]. Do NOT continue reasoning until you see the result.

Available tools:
{tool_descriptions}

After calling tools, you will receive results marked with [Tool Result]. Use those results to continue your work.
If you don't need any tools, respond with regular text (no JSON).
"""


async def _create_process(cmd: List[str], **kwargs) -> asyncio.subprocess.Process:
    """Create subprocess, using shell on Windows for npm .cmd shim compat."""
    if sys.platform == "win32":
        return await asyncio.create_subprocess_shell(" ".join(cmd), **kwargs)
    return await asyncio.create_subprocess_exec(*cmd, **kwargs)


def _format_tools_for_prompt(tools: List[Dict[str, Any]]) -> str:
    """Convert OpenAI tool schemas to a readable description for CLI injection."""
    if not tools:
        return "(none)"

    lines: List[str] = []
    for tool in tools:
        if tool.get("type") != "function":
            continue
        func = tool.get("function", {})
        name = func.get("name", "unknown")
        desc = func.get("description", "")
        params = func.get("parameters", {}).get("properties", {})
        required = func.get("parameters", {}).get("required", [])

        param_strs = []
        for pname, pspec in params.items():
            ptype = pspec.get("type", "string")
            pdesc = pspec.get("description", "")
            req_marker = " (required)" if pname in required else ""
            param_strs.append(f"  - {pname} ({ptype}){req_marker}: {pdesc}")

        lines.append(f"• {name}: {desc}")
        if param_strs:
            lines.extend(param_strs)

    return "\n".join(lines)


def _parse_tool_calls_from_text(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract tool_calls JSON blocks from LLM text output.

    Returns (remaining_text, tool_calls_list).
    Supports multiple formats:
    - ```json\n{"tool_calls": [...]}```
    - {"tool_calls": [...]} (bare JSON)
    - Mixed text + JSON
    """
    tool_calls: List[Dict[str, Any]] = []
    remaining = text

    # Pattern 1: JSON code blocks with tool_calls
    json_block_pattern = r'```(?:json)?\s*\n?(\{[^`]*?"tool_calls"[^`]*?\})\s*```'
    matches = list(re.finditer(json_block_pattern, text, re.DOTALL | re.IGNORECASE))

    for match in matches:
        json_str = match.group(1).strip()
        try:
            data = json.loads(json_str)
            if isinstance(data, dict) and "tool_calls" in data:
                calls = data["tool_calls"]
                if isinstance(calls, list):
                    # Normalize to OpenAI format
                    for call in calls:
                        if isinstance(call, dict) and "name" in call:
                            tool_calls.append({
                                "id": f"call_{len(tool_calls)}",
                                "type": "function",
                                "function": {
                                    "name": call.get("name", ""),
                                    "arguments": json.dumps(call.get("arguments", {})),
                                },
                            })
                # Remove the JSON block from remaining text
                remaining = remaining.replace(match.group(0), "", 1)
        except json.JSONDecodeError:
            continue

    # Pattern 2: Bare JSON objects with tool_calls (no code fence)
    if not tool_calls:
        bare_json_pattern = r'(\{[^{}]*?"tool_calls"[^{}]*?\})'
        bare_matches = list(re.finditer(bare_json_pattern, text, re.DOTALL))
        for match in bare_matches:
            json_str = match.group(1).strip()
            try:
                data = json.loads(json_str)
                if isinstance(data, dict) and "tool_calls" in data:
                    calls = data["tool_calls"]
                    if isinstance(calls, list):
                        for call in calls:
                            if isinstance(call, dict) and "name" in call:
                                tool_calls.append({
                                    "id": f"call_{len(tool_calls)}",
                                    "type": "function",
                                    "function": {
                                        "name": call.get("name", ""),
                                        "arguments": json.dumps(call.get("arguments", {})),
                                    },
                                })
                    remaining = remaining.replace(match.group(0), "", 1)
                    break
            except json.JSONDecodeError:
                continue

    return remaining.strip(), tool_calls


def _parse_codex_jsonl(raw: str) -> str:
    """Extract assistant message content from Codex JSONL (--json) output.

    Handles both the legacy format and the current Codex CLI event format:
    - {"type":"item.completed","item":{"type":"agent_message","text":"..."}}
    - {"type":"message","role":"assistant","content":[{"type":"output_text","text":"..."}]}
    - {"type":"output_text","text":"..."}
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
        if not isinstance(event, dict):
            continue

        # Current Codex CLI format: item.completed with agent_message
        if event.get("type") in ("item.completed", "item.started"):
            item = event.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text", "")
                if text:
                    parts.append(text)
            continue

        # Legacy format: {"role":"assistant","content":[{"type":"output_text","text":"..."}]}
        if event.get("role") == "assistant":
            for part in event.get("content", []):
                if isinstance(part, dict) and part.get("type") == "output_text":
                    parts.append(part.get("text", ""))
            continue

        # Direct text event
        if event.get("type") == "output_text":
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
            import subprocess as _subprocess
            proc = await asyncio.create_subprocess_shell(
                _subprocess.list2cmdline(cmd), stdout=PIPE, stderr=PIPE, env=env
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

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: list | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Implement tool-calling via CLI binary using prompt engineering.

        P2 Innovation: Injects tool schemas into system prompt, prompts the CLI
        to emit tool_calls as JSON, then parses the response. Includes retry
        logic for malformed responses.
        """
        # Build flat prompt with tool-calling instructions injected
        parts: list[str] = []
        tool_descriptions = ""
        if max_tokens is not None:
            logger.debug("[cli-account] max_tokens=%s ignored by CLI account adapter", max_tokens)
        if response_format is not None:
            logger.debug("[cli-account] response_format ignored by CLI account adapter")

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content") or ""

            if role == "system":
                # Inject tool-calling prompt into system message
                if tools:
                    tool_descriptions = _format_tools_for_prompt(tools)
                    tool_prompt = TOOL_CALLING_SYSTEM_PROMPT.format(tool_descriptions=tool_descriptions)
                    parts.append(f"[System]\n{content}\n\n{tool_prompt}")
                else:
                    parts.append(f"[System]\n{content}")
            elif role == "user":
                parts.append(f"[User]\n{content}")
            elif role == "assistant":
                parts.append(f"[Assistant]\n{content}")
            elif role == "tool":
                parts.append(f"[Tool Result]\n{content}")

        prompt = "\n\n".join(parts)

        # First attempt
        result = await self.generate(prompt, {})
        raw_content = result.get("content", "")

        # Parse tool calls from response
        remaining_text, tool_calls = _parse_tool_calls_from_text(raw_content)

        # If no tool_calls found and tools are available, retry with hint
        max_retries = 2
        retry_count = 0

        while not tool_calls and tools and retry_count < max_retries:
            retry_count += 1
            logger.warning(
                f"[cli-account] No valid tool_calls found in response (attempt {retry_count}/{max_retries}). Retrying with hint."
            )

            # Re-prompt with explicit hint
            retry_prompt = (
                f"{prompt}\n\n[Assistant]\n{raw_content}\n\n"
                f"[System]\nYour previous response did not contain valid tool_calls JSON. "
                f"Please respond with ONLY a JSON block in this format:\n"
                f'```json\n{{"tool_calls": [{{"name": "tool_name", "arguments": {{"key": "value"}}}}]}}\n```'
            )

            result = await self.generate(retry_prompt, {})
            raw_content = result.get("content", "")
            remaining_text, tool_calls = _parse_tool_calls_from_text(raw_content)

        # If still no tool_calls after retries, treat as final text response
        if not tool_calls and tools:
            logger.info("[cli-account] No tool_calls found after retries. Treating as final text response.")

        return {
            "content": remaining_text or raw_content,
            "tool_calls": tool_calls,
            "usage": result.get("usage", {}),
            "finish_reason": "stop" if not tool_calls else "tool_calls",
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
