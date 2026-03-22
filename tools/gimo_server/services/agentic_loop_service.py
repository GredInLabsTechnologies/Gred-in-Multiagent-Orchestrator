"""AgenticLoopService — core motor for GIMO agentic chat.

Orchestrates a multi-turn LLM loop with tool execution and governance.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..engine.tools.chat_tools_schema import CHAT_TOOLS, get_tool_risk_level
from ..engine.tools.executor import ToolExecutionResult, ToolExecutor
from ..ops_models import GimoItem, GimoTurn
from ..providers.base import ProviderAdapter
from ..services.conversation_service import ConversationService
from ..services.cost_service import CostService
from ..services.notification_service import NotificationService
from ..services.provider_auth_service import ProviderAuthService
from ..services.provider_service_adapter_registry import build_provider_adapter
from ..services.provider_service_impl import ProviderService

logger = logging.getLogger("orchestrator.agentic_loop")

MAX_TURNS = 25
MAX_TOOLS_PER_RESPONSE = 10
TOOL_TIMEOUT_SECONDS = 30

SYSTEM_PROMPT_TEMPLATE = """You are GIMO, a governance-aware coding orchestrator.
You help users with software engineering tasks by reading, writing, and searching code.

Workspace: {workspace_root}
Project structure:
{tree}

Available tools: read_file, write_file, patch_file, search_replace, list_files, search_text, shell_exec, create_dir

Guidelines:
- Always read a file before modifying it
- Prefer search_replace over write_file for editing existing files
- Use shell_exec only when file tools are insufficient
- Keep changes minimal and focused on what the user asked
- Explain what you're doing as you work
"""


@dataclass
class ToolCallLog:
    name: str
    arguments: Dict[str, Any]
    result_status: str
    result_message: str
    risk_level: str
    duration_seconds: float


@dataclass
class AgenticResult:
    response: str
    tool_calls_log: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    turns_used: int = 0
    finish_reason: str = "stop"


def _generate_workspace_tree(workspace_root: str, max_depth: int = 2, max_entries: int = 100) -> str:
    """Generate a simple tree representation of the workspace."""
    root = Path(workspace_root)
    if not root.exists():
        return "(workspace not found)"

    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".gimo"}
    lines: List[str] = []

    def _walk(path: Path, depth: int, prefix: str) -> None:
        if len(lines) >= max_entries or depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return
        for entry in entries:
            if entry.name.startswith(".") and entry.name not in {".env.example"}:
                if entry.name in skip_dirs or entry.is_dir():
                    continue
            if entry.name in skip_dirs:
                continue
            if len(lines) >= max_entries:
                lines.append(f"{prefix}... (truncated)")
                return
            if entry.is_dir():
                lines.append(f"{prefix}{entry.name}/")
                _walk(entry, depth + 1, prefix + "  ")
            else:
                lines.append(f"{prefix}{entry.name}")

    _walk(root, 0, "  ")
    return "\n".join(lines) if lines else "(empty workspace)"


def _build_messages_from_thread(thread_turns: List[GimoTurn], system_prompt: str) -> List[Dict[str, Any]]:
    """Convert thread turns into OpenAI-compatible messages list."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    for turn in thread_turns:
        if turn.agent_id in ("user", "User"):
            for item in turn.items:
                if item.type == "text" and item.content:
                    messages.append({"role": "user", "content": item.content})
        elif turn.agent_id == "orchestrator":
            # Reconstruct assistant messages with tool_calls
            pending_tool_calls: List[Dict[str, Any]] = []
            for item in turn.items:
                if item.type == "text" and item.content:
                    msg: Dict[str, Any] = {"role": "assistant", "content": item.content}
                    if pending_tool_calls:
                        msg["tool_calls"] = pending_tool_calls
                        pending_tool_calls = []
                    messages.append(msg)
                elif item.type == "tool_call":
                    tc_meta = item.metadata or {}
                    pending_tool_calls.append({
                        "id": tc_meta.get("tool_call_id", item.id),
                        "type": "function",
                        "function": {
                            "name": tc_meta.get("tool_name", ""),
                            "arguments": item.content,
                        },
                    })
                elif item.type == "tool_result":
                    tc_meta = item.metadata or {}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_meta.get("tool_call_id", item.id),
                        "content": item.content,
                    })

            # If there were tool_calls without a preceding text message
            if pending_tool_calls:
                messages.append({"role": "assistant", "content": None, "tool_calls": pending_tool_calls})

    return messages


def _resolve_orchestrator_adapter() -> tuple[ProviderAdapter, str, str]:
    """Resolve the orchestrator provider and build an adapter.

    Returns: (adapter, provider_id, model)
    """
    cfg = ProviderService.get_config()
    if not cfg:
        raise RuntimeError("Provider config not found. Run gimo init or configure providers.")

    roles = cfg.roles
    if not roles or not roles.orchestrator:
        raise RuntimeError("No orchestrator role configured in provider.json")

    orch = roles.orchestrator
    provider_id = orch.provider_id
    model = orch.model

    entry = cfg.providers.get(provider_id)
    if not entry:
        raise RuntimeError(f"Orchestrator provider '{provider_id}' not found in providers")

    canonical_type = ProviderService.normalize_provider_type(entry.type)
    adapter = build_provider_adapter(
        entry=entry,
        canonical_type=canonical_type,
        resolve_secret=ProviderAuthService.resolve_secret,
    )
    return adapter, provider_id, model


class AgenticLoopService:
    """Runs the agentic loop: LLM -> tool_calls -> execute -> repeat."""

    @staticmethod
    async def run(
        thread_id: str,
        user_message: str,
        workspace_root: str,
        token: str = "system",
    ) -> AgenticResult:
        # 1. Resolve orchestrator
        adapter, provider_id, model = _resolve_orchestrator_adapter()

        # 2. Save user message
        user_turn = ConversationService.add_turn(thread_id, agent_id="user")
        if not user_turn:
            raise RuntimeError(f"Thread {thread_id} not found")
        user_item = GimoItem(type="text", content=user_message, status="completed")
        ConversationService.append_item(thread_id, user_turn.id, user_item)

        # 3. Build system prompt
        tree = _generate_workspace_tree(workspace_root)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(workspace_root=workspace_root, tree=tree)

        # 4. Build messages from thread history
        thread = ConversationService.get_thread(thread_id)
        if not thread:
            raise RuntimeError(f"Thread {thread_id} disappeared")
        messages = _build_messages_from_thread(thread.turns, system_prompt)

        # 5. Setup executor
        executor = ToolExecutor(workspace_root=workspace_root, token=token)

        # 6. Agentic loop
        total_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        all_tool_logs: List[Dict[str, Any]] = []
        final_response = ""
        iterations_used = 0
        finish_reason = "stop"

        for iteration in range(MAX_TURNS):
            iterations_used = iteration + 1
            # Call LLM
            try:
                llm_result = await adapter.chat_with_tools(
                    messages=messages,
                    tools=CHAT_TOOLS,
                    temperature=0.0,
                )
            except Exception as exc:
                logger.error(f"LLM call failed on iteration {iteration}: {exc}")
                final_response = f"Error communicating with LLM: {exc}"
                break

            # Accumulate usage
            usage = llm_result.get("usage", {})
            for key in total_usage:
                total_usage[key] += usage.get(key, 0)

            content = llm_result.get("content")
            tool_calls = llm_result.get("tool_calls", [])
            finish_reason = llm_result.get("finish_reason", "stop")

            # No tool_calls -> final response
            if not tool_calls:
                final_response = content or ""
                break

            # Process tool_calls
            # Build assistant message with tool_calls for history
            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": content, "tool_calls": tool_calls}
            messages.append(assistant_msg)

            # Create orchestrator turn for this iteration
            orch_turn = ConversationService.add_turn(thread_id, agent_id="orchestrator")
            if not orch_turn:
                break

            # If there's text content alongside tool_calls, save it
            if content:
                text_item = GimoItem(type="text", content=content, status="completed")
                ConversationService.append_item(thread_id, orch_turn.id, text_item)

            for tc in tool_calls[:MAX_TOOLS_PER_RESPONSE]:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                tool_call_id = tc.get("id", "")

                # Parse arguments
                raw_args = func.get("arguments", "{}")
                try:
                    tool_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    tool_args = {}

                # Governance check
                risk = get_tool_risk_level(tool_name)
                logger.info(f"Tool call: {tool_name} risk={risk} args={list(tool_args.keys())}")

                # Save tool_call item
                tc_item = GimoItem(
                    type="tool_call",
                    content=json.dumps(tool_args),
                    status="started",
                    metadata={"tool_name": tool_name, "tool_call_id": tool_call_id, "risk": risk},
                )
                ConversationService.append_item(thread_id, orch_turn.id, tc_item)

                # Execute tool
                start_time = time.monotonic()
                result = await executor.execute_tool_call(tool_name, tool_args)
                duration = time.monotonic() - start_time

                result_status = result.get("status", "error")
                result_message = result.get("message", "")
                result_data = result.get("data", {})

                # Build tool result content for LLM
                tool_result_content = result_message
                if result_data:
                    # Include relevant data but truncate large content
                    data_str = json.dumps(result_data, ensure_ascii=False)
                    if len(data_str) > 8000:
                        data_str = data_str[:8000] + "... (truncated)"
                    tool_result_content = f"{result_message}\n{data_str}"

                # Save tool_result item
                tr_item = GimoItem(
                    type="tool_result",
                    content=tool_result_content,
                    status="completed" if result_status == "success" else "error",
                    metadata={"tool_call_id": tool_call_id, "tool_name": tool_name, "duration": round(duration, 3)},
                )
                ConversationService.append_item(thread_id, orch_turn.id, tr_item)

                # Append tool result to messages for LLM
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": tool_result_content,
                })

                # Log
                tool_log = ToolCallLog(
                    name=tool_name,
                    arguments=tool_args,
                    result_status=result_status,
                    result_message=result_message,
                    risk_level=risk,
                    duration_seconds=round(duration, 3),
                )
                all_tool_logs.append({
                    "name": tool_log.name,
                    "arguments": tool_log.arguments,
                    "status": tool_log.result_status,
                    "message": tool_log.result_message,
                    "risk": tool_log.risk_level,
                    "duration": tool_log.duration_seconds,
                })

                # Broadcast SSE
                try:
                    await NotificationService.publish("tool_executed", {
                        "thread_id": thread_id,
                        "tool_name": tool_name,
                        "status": result_status,
                        "risk": risk,
                        "duration": round(duration, 3),
                    })
                except Exception:
                    pass  # SSE broadcast is best-effort

        else:
            # Loop exhausted MAX_TURNS
            final_response = "(Reached maximum iterations. Stopping.)"

        # 7. Save final response
        final_turn = ConversationService.add_turn(thread_id, agent_id="orchestrator")
        if final_turn and final_response:
            final_item = GimoItem(type="text", content=final_response, status="completed")
            ConversationService.append_item(thread_id, final_turn.id, final_item)

        # 8. Calculate cost
        try:
            cost_usd = CostService.calculate_cost(
                model=model,
                input_tokens=total_usage.get("prompt_tokens", 0),
                output_tokens=total_usage.get("completion_tokens", 0),
            )
            total_usage["cost_usd"] = cost_usd
        except Exception:
            pass  # Cost tracking is best-effort

        return AgenticResult(
            response=final_response,
            tool_calls_log=all_tool_logs,
            usage=total_usage,
            turns_used=iterations_used,
            finish_reason=finish_reason,
        )
