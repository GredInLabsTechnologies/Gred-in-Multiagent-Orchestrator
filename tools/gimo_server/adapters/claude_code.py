from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from .base import (
    AgentAdapter, 
    AgentSession, 
    ProposedAction
)
from .generic_cli import GenericCLISession

logger = logging.getLogger("orchestrator.adapters.claude_code")


class ClaudeCodeSession(GenericCLISession):
    """Session for Claude Code agent.
    
    Extends GenericCLISession to add MCP-specific interception logic.
    """

    MCP_PRE_TOOL_PREFIX = "MCP_PRE_TOOL:"
    METRICS_PREFIX = "METRICS:"
    ALLOW_CMD_PREFIX = "MCP_ALLOW"
    DENY_CMD_PREFIX = "MCP_DENY"

    def _handle_stdout_line(self, line: str) -> None:
        """Parse Claude-specific protocol lines.

        Supported lines:
        - MCP_PRE_TOOL:{"id":"...","tool":"...","params":{...},"description":"..."}
        - METRICS:{"tokens_used":123,"duration_ms":456}
        """
        if line.startswith(self.MCP_PRE_TOOL_PREFIX):
            payload = line[len(self.MCP_PRE_TOOL_PREFIX):].strip()
            # Reuse GenericCLI proposal parser by mapping to PROPOSAL protocol.
            super()._handle_stdout_line(f"{self.PROPOSAL_PREFIX}{payload}")
            return

        if line.startswith(self.METRICS_PREFIX):
            raw_payload = line[len(self.METRICS_PREFIX):].strip()
            try:
                metrics = json.loads(raw_payload)
                if isinstance(metrics, dict):
                    self._metrics.update(metrics)
            except json.JSONDecodeError as exc:
                logger.warning("Invalid metrics payload ignored: %s", exc)
            return

        super()._handle_stdout_line(line)

    async def capture_proposals(self) -> List[ProposedAction]:
        """Return currently intercepted MCP pre-tool proposals."""
        return await super().capture_proposals()

    async def allow(self, action_id: str) -> None:
        """Tell Claude Code to proceed with the action via MCP-compatible command."""
        await super().allow(action_id)

    async def deny(self, action_id: str, reason: Optional[str] = None) -> None:
        """Tell Claude Code to abort the action via MCP-compatible command."""
        await super().deny(action_id, reason)


class ClaudeCodeAdapter(AgentAdapter):
    """Adapter for orchestrating Claude Code.

    Spawns the `claude` CLI and handles the MCP protocol over stdio.
    """

    def __init__(
        self,
        binary_path: str = "claude",
        *,
        trust_event_sink: Optional[Any] = None,
        model_name: str = "claude-code",
        actor: str = "agent:claude_code",
    ):
        self.binary_path = binary_path
        self.trust_event_sink = trust_event_sink
        self.model_name = model_name
        self.actor = actor

    async def spawn(
        self, 
        task: str, 
        context: Optional[Dict[str, Any]] = None, 
        policy: Optional[Dict[str, Any]] = None
    ) -> AgentSession:
        logger.info(f"Spawning Claude Code: {self.binary_path}")

        command = [self.binary_path, "execute", task, "--output-format", "stream-json"]
        if context:
            command.extend(["--context", json.dumps(context)])
        if policy:
            command.extend(["--policy", json.dumps(policy)])
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        task_type = str((context or {}).get("task_type") or (policy or {}).get("task_type") or "agent_task")
        role_profile = str((context or {}).get("role_profile") or (policy or {}).get("role_profile") or "").strip() or None
        hitl_enabled = bool((context or {}).get("hitl_enabled") or (policy or {}).get("hitl_enabled") or False)
        hitl_timeout = float((context or {}).get("hitl_timeout_seconds") or (policy or {}).get("hitl_timeout_seconds") or 300.0)
        return ClaudeCodeSession(
            process,
            task,
            trust_event_sink=self.trust_event_sink,
            model_name=self.model_name,
            task_type=task_type,
            actor=self.actor,
            role_profile=role_profile,
            hitl_enabled=hitl_enabled,
            hitl_timeout_seconds=hitl_timeout,
        )
