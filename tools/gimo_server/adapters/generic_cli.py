from __future__ import annotations

import asyncio
import logging
import json
import inspect
import time
from typing import Any, Dict, List, Optional

from .base import (
    AgentAdapter, 
    AgentResult, 
    AgentSession, 
    AgentStatus, 
    ProposedAction
)
from ..services.policy_service import PolicyService
from ..services.storage_service import StorageService
from ..services.trust_engine import TrustEngine
from ..services.tool_registry_service import ToolRegistryService
from ..services.hitl_gate_service import HitlGateService
from ..models.agent_routing import RoutingDecisionSummary

logger = logging.getLogger("orchestrator.adapters.generic_cli")


class GenericCLISession(AgentSession):
    """Session for a generic CLI agent via stdin/stdout.

    Implements the standard specific agent protocol:
    - Listens for `PROPOSAL:{json}` on stdout.
    - Sends `ALLOW {id}` or `DENY {id}` to stdin.
    - Parses metrics and status updates.
    """

    PROPOSAL_PREFIX = "PROPOSAL:"
    ALLOW_CMD_PREFIX = "ALLOW"
    DENY_CMD_PREFIX = "DENY"

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        task: str,
        *,
        trust_event_sink: Optional[Any] = None,
        model_name: str = "generic-cli",
        task_type: str = "agent_task",
        actor: str = "agent:generic_cli",
        role_profile: Optional[str] = None,
        routing_summary: Optional[RoutingDecisionSummary] = None,
        hitl_enabled: bool = False,
        hitl_timeout_seconds: float = 300.0,
    ):
        self.process = process
        self.task = task
        self.status = AgentStatus.RUNNING
        self.created_at = time.perf_counter()
        self._output_buffer: List[str] = []
        self._error_buffer: List[str] = []
        self._proposals: List[ProposedAction] = []
        self._proposal_index: Dict[str, ProposedAction] = {}
        self._decision_log: Dict[str, str] = {}
        self._metrics: Dict[str, Any] = {}
        self._trust_event_sink = trust_event_sink
        self._model_name = model_name
        self._task_type = task_type
        self._actor = actor

        # Prefer explicit execution_policy from canonical routing.  Legacy
        # role_profile survives only as a behavior tag, never as a permission
        # source of truth.
        if routing_summary:
            from ..services.execution.execution_policy_service import ExecutionPolicyService
            self._execution_policy = ExecutionPolicyService.get_policy(routing_summary.execution_policy)
            self._role_profile = routing_summary.mood  # For legacy compatibility
        elif role_profile:
            # Backward compatibility: derive from role_profile
            from ..services.execution.execution_policy_service import ExecutionPolicyService
            policy_name = ExecutionPolicyService.policy_name_from_legacy_mood(role_profile)
            self._execution_policy = ExecutionPolicyService.get_policy(policy_name)
            self._role_profile = role_profile
        else:
            # Default fallback
            from ..services.execution.execution_policy_service import ExecutionPolicyService
            self._execution_policy = ExecutionPolicyService.get_policy("workspace_safe")
            self._role_profile = "executor"

        self._hitl_enabled = hitl_enabled
        self._hitl_timeout_seconds = float(hitl_timeout_seconds)

        # Start background readers
        self._read_task = asyncio.create_task(self._read_streams())

    async def _read_streams(self):
        async def _read_stdout() -> None:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                decoded = line.decode(errors="replace").strip()
                if not decoded:
                    continue
                self._output_buffer.append(decoded)
                self._handle_stdout_line(decoded)

        async def _read_stderr() -> None:
            while True:
                line = await self.process.stderr.readline()
                if not line:
                    break
                decoded = line.decode(errors="replace").strip()
                if not decoded:
                    continue
                self._error_buffer.append(decoded)

        try:
            await asyncio.gather(_read_stdout(), _read_stderr())
        except Exception as e:
            logger.error("Error reading from process: %s", e)
            self.status = AgentStatus.FAILED

    def _handle_stdout_line(self, line: str) -> None:
        """Parse protocol lines emitted by CLI adapters.

        Protocol:
        - PROPOSAL:{json}
          Example JSON:
            {"id":"a1","tool":"file_write","params":{"path":"x.py"},"description":"..."}
        """
        if not line.startswith(self.PROPOSAL_PREFIX):
            return

        raw_payload = line[len(self.PROPOSAL_PREFIX):].strip()
        if not raw_payload:
            return

        try:
            payload = json.loads(raw_payload)
            action = ProposedAction(
                id=str(payload["id"]),
                tool=str(payload["tool"]),
                params=dict(payload.get("params", {})),
                description=payload.get("description"),
            )
            # Dynamic discovery feed (still fail-closed by default via admin-only discovered entries).
            try:
                ToolRegistryService.report_tool(
                    name=action.tool,
                    description=action.description or "",
                    risk=str(action.params.get("risk") or "read"),
                )
            except Exception:
                # Discovery must never break runtime parsing.
                pass
            if action.id not in self._proposal_index:
                self._proposal_index[action.id] = action
                self._proposals.append(action)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Invalid proposal payload ignored: %s", exc)

    async def _send_stdin_line(self, line: str) -> None:
        if not self.process.stdin:
            return

        maybe_awaitable = self.process.stdin.write(f"{line}\n".encode())
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
        await self.process.stdin.drain()

    async def get_status(self) -> AgentStatus:
        if self.process.returncode is not None:
            if self.process.returncode == 0:
                self.status = AgentStatus.COMPLETED
            else:
                self.status = AgentStatus.FAILED
        return self.status

    async def capture_proposals(self) -> List[ProposedAction]:
        # Return a copy to avoid callers mutating the internal buffer
        return list(self._proposals)

    async def allow(self, action_id: str) -> None:
        if action_id not in self._proposal_index:
            raise ValueError(f"Unknown proposal id: {action_id}")
        action = self._proposal_index[action_id]

        # F7.1: Use execution_policy directly instead of role_profiles
        try:
            self._execution_policy.assert_tool_allowed(action.tool)
        except PermissionError:
            self._decision_log[action_id] = "blocked:execution_policy_denied"
            await self._send_stdin_line(f"{self.DENY_CMD_PREFIX} {action_id} reason=execution_policy_denied")
            self._emit_trust_event(action_id=action_id, outcome="rejected")
            raise

        # Check HITL requirement (if execution_policy enforces it)
        if self._execution_policy.hitl_required and self._hitl_enabled:
            gate_decision = await HitlGateService.gate_tool_call(
                agent_id=self._actor,
                tool=action.tool,
                params=dict(action.params or {}),
                timeout_seconds=self._hitl_timeout_seconds,
            )
            if gate_decision != "allow":
                self._decision_log[action_id] = "blocked:hitl_rejected"
                await self._send_stdin_line(f"{self.DENY_CMD_PREFIX} {action_id} reason=hitl_rejected")
                self._emit_trust_event(action_id=action_id, outcome="rejected")
                raise PermissionError(f"HITL denied tool execution: {action.tool}")
        
        await self._validate_tool_registry(action, action_id)
        tool_entry = ToolRegistryService.get_tool(action.tool)
        
        await self._validate_idempotency(action, action_id, tool_entry)
        
        await self._validate_policy(action, action_id)

        self._decision_log[action_id] = "allowed"
        await self._send_stdin_line(f"{self.ALLOW_CMD_PREFIX} {action_id}")
        self._emit_trust_event(action_id=action_id, outcome="approved")

    async def _validate_tool_registry(self, action: ProposedAction, action_id: str) -> None:
        if not ToolRegistryService.is_allowed(action.tool):
            self._decision_log[action_id] = "blocked:not_in_tool_registry"
            await self._send_stdin_line(f"{self.DENY_CMD_PREFIX} {action_id} reason=tool_not_registered")
            self._emit_trust_event(action_id=action_id, outcome="rejected")
            raise PermissionError(f"Tool not registered: {action.tool}")

    async def _validate_idempotency(self, action: ProposedAction, action_id: str, tool_entry: Any) -> None:
        risk = str(getattr(tool_entry, "risk", "read") or "read")
        if risk not in {"write", "destructive"}:
            return

        idem_key = str(action.params.get("idempotency_key") or "").strip()
        if not idem_key:
            self._decision_log[action_id] = "blocked:missing_idempotency_key"
            await self._send_stdin_line(f"{self.DENY_CMD_PREFIX} {action_id} reason=missing_idempotency_key")
            self._emit_trust_event(action_id=action_id, outcome="rejected")
            raise PermissionError(f"Missing idempotency_key for {risk} tool: {action.tool}")

        accepted = StorageService().register_tool_call_idempotency_key(
            idempotency_key=idem_key,
            tool=action.tool,
            context=str(action.params.get("path") or action.params.get("cmd") or "*"),
        )
        if not accepted:
            self._decision_log[action_id] = "blocked:duplicate_idempotency_key"
            await self._send_stdin_line(f"{self.DENY_CMD_PREFIX} {action_id} reason=duplicate_idempotency_key")
            self._emit_trust_event(action_id=action_id, outcome="rejected")
            raise PermissionError(f"Duplicate idempotency_key for tool call: {action.tool}")

    async def _validate_policy(self, action: ProposedAction, action_id: str) -> None:
        context_value = str(action.params.get("path") or action.params.get("cmd") or "*")
        dimension_key = f"{action.tool}|*|{self._model_name}|{self._task_type}"
        trust_score = 0.0
        try:
            trust_score = float(
                TrustEngine(StorageService()).query_dimension(dimension_key).get("score", 0.0) or 0.0
            )
        except Exception as exc:
            logger.warning("Trust query failed for %s: %s", dimension_key, exc)

        policy_decision = PolicyService.decide(
            tool=action.tool,
            context=context_value,
            trust_score=trust_score,
        )

        if policy_decision.get("decision") == "deny":
            self._decision_log[action_id] = "blocked:policy_deny"
            await self._send_stdin_line(f"{self.DENY_CMD_PREFIX} {action_id} reason=policy_deny")
            self._emit_trust_event(action_id=action_id, outcome="rejected")
            raise PermissionError(f"Policy denied tool execution: {action.tool}")

        if policy_decision.get("decision") == "require_review":
            self._decision_log[action_id] = "blocked:policy_require_review"
            await self._send_stdin_line(f"{self.DENY_CMD_PREFIX} {action_id} reason=policy_require_review")
            self._emit_trust_event(action_id=action_id, outcome="rejected")
            raise PermissionError(f"Policy requires review for tool execution: {action.tool}")

        if (
            policy_decision.get("override") == "never_auto_approve"
            and trust_score >= 0.90
        ):
            self._decision_log[action_id] = "blocked:policy_never_auto_approve"
            await self._send_stdin_line(f"{self.DENY_CMD_PREFIX} {action_id} reason=policy_never_auto_approve")
            self._emit_trust_event(action_id=action_id, outcome="rejected")
            raise PermissionError(f"Policy override requires manual review: {action.tool}")

    async def deny(self, action_id: str, reason: Optional[str] = None) -> None:
        if action_id not in self._proposal_index:
            raise ValueError(f"Unknown proposal id: {action_id}")
        self._decision_log[action_id] = f"denied:{reason or ''}"
        message = f"{self.DENY_CMD_PREFIX} {action_id}"
        if reason:
            message += f" reason={reason}"
        await self._send_stdin_line(message)
        self._emit_trust_event(action_id=action_id, outcome="rejected")

    def _emit_trust_event(self, *, action_id: str, outcome: str) -> None:
        if not self._trust_event_sink:
            return
        action = self._proposal_index.get(action_id)
        if not action:
            return

        event = {
            "dimension_key": f"{action.tool}|*|{self._model_name}|{self._task_type}",
            "tool": action.tool,
            "context": str(action.params.get("path") or action.params.get("cmd") or "*"),
            "model": self._model_name,
            "task_type": self._task_type,
            "outcome": outcome,
            "actor": self._actor,
            "post_check_passed": outcome == "approved",
            "duration_ms": int((time.perf_counter() - self.created_at) * 1000),
            "tokens_used": int(self._metrics.get("tokens_used", 0) or 0),
            "cost_usd": float(self._metrics.get("cost_usd", 0.0) or 0.0),
        }
        try:
            self._trust_event_sink(event)
        except Exception as exc:
            logger.warning("Failed to emit trust event: %s", exc)

    async def get_result(self) -> AgentResult:
        await self.process.wait()
        status = await self.get_status()
        return AgentResult(
            status=status,
            output="\n".join(self._output_buffer),
            metrics={
                "stderr": "\n".join(self._error_buffer),
                "proposal_count": len(self._proposals),
                "decisions": dict(self._decision_log),
                **self._metrics,
            },
            error="\n".join(self._error_buffer) if status == AgentStatus.FAILED else None
        )

    async def kill(self) -> None:
        if self.process.returncode is None:
            self.process.kill()
            self.status = AgentStatus.KILLED


class GenericCLIAdapter(AgentAdapter):
    """Adapter for spawning generic CLI processes."""

    def __init__(
        self,
        command: List[str],
        *,
        trust_event_sink: Optional[Any] = None,
        model_name: str = "generic-cli",
        actor: str = "agent:generic_cli",
    ):
        self.command = command
        self.trust_event_sink = trust_event_sink
        self.model_name = model_name
        self.actor = actor
        self.role_profile: Optional[str] = None
        self.hitl_enabled: bool = False
        self.hitl_timeout_seconds: float = 300.0

    async def spawn(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        policy: Optional[Dict[str, Any]] = None,
        routing_summary: Optional[RoutingDecisionSummary] = None,
    ) -> AgentSession:
        logger.info(f"Spawning generic CLI: {' '.join(self.command)}")

        process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Feed task to stdin
        if process.stdin:
            maybe_awaitable = process.stdin.write(f"{task}\n".encode())
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
            await process.stdin.drain()

        # F7.1: Extract role_profile for backward compatibility if no routing_summary
        task_type = str((context or {}).get("task_type") or (policy or {}).get("task_type") or "agent_task")
        role_profile = None
        if not routing_summary:
            role_profile = str((context or {}).get("role_profile") or (policy or {}).get("role_profile") or "").strip() or None
        hitl_enabled = bool((context or {}).get("hitl_enabled") or (policy or {}).get("hitl_enabled") or self.hitl_enabled)
        hitl_timeout = float((context or {}).get("hitl_timeout_seconds") or (policy or {}).get("hitl_timeout_seconds") or self.hitl_timeout_seconds)

        return GenericCLISession(
            process,
            task,
            trust_event_sink=self.trust_event_sink,
            model_name=self.model_name,
            task_type=task_type,
            actor=self.actor,
            role_profile=role_profile,
            routing_summary=routing_summary,
            hitl_enabled=hitl_enabled,
            hitl_timeout_seconds=hitl_timeout,
        )
