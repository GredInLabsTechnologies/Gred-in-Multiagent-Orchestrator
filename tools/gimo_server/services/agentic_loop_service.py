"""AgenticLoopService — core motor for GIMO agentic chat.

Orchestrates a multi-turn LLM loop with tool execution and governance.

P2: Enhanced with mood-driven conversational flow, meta-tools (ask_user, propose_plan),
and pause/resume for human-in-the-loop approval.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from ..engine.moods import get_mood_profile, MoodProfile  # P2
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

MAX_TURNS = 25  # Default, overridden by mood profile
MAX_TOOLS_PER_RESPONSE = 10
TOOL_TIMEOUT_SECONDS = 30
HITL_APPROVAL_TIMEOUT = 300  # 5 minutes to approve/deny a HIGH risk tool

# P2: Updated system prompt with conversational planning instructions
SYSTEM_PROMPT_TEMPLATE = """You are GIMO, a governance-aware coding orchestrator.
You help users with software engineering tasks by reading, writing, and searching code.

Workspace: {workspace_root}
Project structure:
{tree}

Available tools: read_file, write_file, patch_file, search_replace, list_files, search_text, shell_exec, create_dir, ask_user, propose_plan, web_search

## Conversational Planning (P2)

For COMPLEX tasks (3+ files, new projects, structural refactors):
1. Ask clarifying questions with ask_user if anything is ambiguous
2. Investigate the workspace and research if needed (read_file, list_files, web_search)
3. Propose a plan with propose_plan — explain WHY you chose each mood and model for each task
4. Wait for user approval before executing

For SIMPLE tasks (1-2 files, quick fixes):
- Execute directly with the file tools

Guidelines:
- Always read a file before modifying it
- Prefer search_replace over write_file for editing existing files
- Use shell_exec only when file tools are insufficient
- Keep changes minimal and focused on what the user asked
- Explain what you're doing as you work

{mood_prefix}
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

    # Pending HITL approvals: {approval_key: asyncio.Event}
    _pending_approvals: Dict[str, asyncio.Event] = {}
    _approval_results: Dict[str, bool] = {}  # True=approved, False=denied

    @classmethod
    def submit_approval(cls, thread_id: str, tool_call_id: str, approved: bool) -> bool:
        """Submit a HITL approval/denial for a pending tool call."""
        key = f"{thread_id}:{tool_call_id}"
        event = cls._pending_approvals.get(key)
        if not event:
            return False
        cls._approval_results[key] = approved
        event.set()
        return True

    @classmethod
    async def _request_approval(cls, thread_id: str, tool_call_id: str, tool_name: str, tool_args: Dict[str, Any]) -> bool:
        """Request HITL approval for a HIGH risk tool. Returns True if approved."""
        key = f"{thread_id}:{tool_call_id}"
        event = asyncio.Event()
        cls._pending_approvals[key] = event

        # Broadcast approval request
        await NotificationService.publish("tool_approval_required", {
            "thread_id": thread_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": tool_args,
            "risk": "HIGH",
            "critical": True,
        })

        try:
            await asyncio.wait_for(event.wait(), timeout=HITL_APPROVAL_TIMEOUT)
            return cls._approval_results.pop(key, False)
        except asyncio.TimeoutError:
            logger.warning("HITL approval timed out for %s in thread %s", tool_name, thread_id)
            return False
        finally:
            cls._pending_approvals.pop(key, None)
            cls._approval_results.pop(key, None)

    @staticmethod
    async def run(
        thread_id: str,
        user_message: str,
        workspace_root: str,
        token: str = "system",
    ) -> AgenticResult:
        # 1. Resolve orchestrator
        adapter, provider_id, model = _resolve_orchestrator_adapter()

        # 2. Get thread and mood profile (P2)
        thread = ConversationService.get_thread(thread_id)
        if not thread:
            raise RuntimeError(f"Thread {thread_id} not found")

        mood = thread.mood or "neutral"
        try:
            mood_profile = get_mood_profile(mood)
        except KeyError:
            logger.warning(f"Invalid mood '{mood}', using neutral")
            mood_profile = get_mood_profile("neutral")
            mood = "neutral"

        logger.info(f"[agentic-loop] Running with mood={mood}, temperature={mood_profile.temperature}, max_turns={mood_profile.max_turns}")

        # 3. Save user message
        user_turn = ConversationService.add_turn(thread_id, agent_id="user")
        if not user_turn:
            raise RuntimeError(f"Thread {thread_id} not found after adding turn")
        user_item = GimoItem(type="text", content=user_message, status="completed")
        ConversationService.append_item(thread_id, user_turn.id, user_item)

        # 4. Build system prompt with mood injection (P2)
        tree = _generate_workspace_tree(workspace_root)
        mood_prefix = mood_profile.prompt_prefix or ""
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            workspace_root=workspace_root,
            tree=tree,
            mood_prefix=mood_prefix
        )

        # 5. Build messages from thread history
        messages = _build_messages_from_thread(thread.turns, system_prompt)

        # 6. Setup executor with mood (P2)
        executor = ToolExecutor(workspace_root=workspace_root, token=token, mood=mood)

        # 7. Agentic loop (P2: mood-driven)
        total_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        all_tool_logs: List[Dict[str, Any]] = []
        final_response = ""
        iterations_used = 0
        finish_reason = "stop"
        max_turns = mood_profile.max_turns

        for iteration in range(max_turns):
            iterations_used = iteration + 1
            # Call LLM with mood temperature (P2)
            try:
                llm_result = await adapter.chat_with_tools(
                    messages=messages,
                    tools=CHAT_TOOLS,
                    temperature=mood_profile.temperature,
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

                # HITL gate for HIGH risk tools
                if risk == "HIGH":
                    approved = await AgenticLoopService._request_approval(
                        thread_id, tool_call_id, tool_name, tool_args
                    )
                    if not approved:
                        result = {"status": "denied", "message": f"Tool '{tool_name}' was denied by user (HITL)."}
                        duration = 0.0
                        # Save denial and skip execution
                        tr_item = GimoItem(
                            type="tool_result",
                            content=result["message"],
                            status="error",
                            metadata={"tool_call_id": tool_call_id, "tool_name": tool_name, "duration": 0.0, "hitl": "denied"},
                        )
                        ConversationService.append_item(thread_id, orch_turn.id, tr_item)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result["message"],
                        })
                        all_tool_logs.append({
                            "name": tool_name, "arguments": tool_args,
                            "status": "denied", "message": result["message"],
                            "risk": risk, "duration": 0.0,
                        })
                        continue

                # Execute tool with timeout
                start_time = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        executor.execute_tool_call(tool_name, tool_args),
                        timeout=TOOL_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    result = {"status": "error", "message": f"Tool '{tool_name}' timed out after {TOOL_TIMEOUT_SECONDS}s"}
                duration = time.monotonic() - start_time

                result_status = result.get("status", "error")
                result_message = result.get("message", "")
                result_data = result.get("data", {})

                # P2: Handle special statuses (ask_user, propose_plan, requires_confirmation)
                if result_status == "user_question":
                    # Pause loop, save question, wait for user response
                    logger.info(f"[agentic-loop] User question triggered: {result_data.get('question')}")
                    # Save as special item
                    question_item = GimoItem(
                        type="text",
                        content=f"[QUESTION] {result_data.get('question', result_message)}",
                        status="completed",
                        metadata={"awaiting_user_response": True, "question_data": result_data},
                    )
                    ConversationService.append_item(thread_id, orch_turn.id, question_item)

                    # The loop will continue in the next user message
                    final_response = f"⏸️ Waiting for your answer to: {result_data.get('question', result_message)}"
                    finish_reason = "user_question"
                    break

                if result_status == "plan_proposed":
                    # Pause loop, save plan to thread, wait for approval
                    logger.info(f"[agentic-loop] Plan proposed: {result_data.get('title')}")
                    thread.proposed_plan = result_data
                    ConversationService.save_thread(thread)

                    # Save plan proposal as item
                    plan_item = GimoItem(
                        type="text",
                        content=f"[PLAN PROPOSED] {result_data.get('title', 'Execution Plan')}",
                        status="completed",
                        metadata={"plan": result_data},
                    )
                    ConversationService.append_item(thread_id, orch_turn.id, plan_item)

                    # Emit SSE event
                    try:
                        await NotificationService.publish("plan_proposed", {
                            "thread_id": thread_id,
                            "plan": result_data,
                        })
                    except Exception:
                        pass

                    final_response = f"⏸️ Plan proposed. Please review and approve to continue."
                    finish_reason = "plan_proposed"
                    break

                if result_status == "requires_confirmation":
                    # Tool requires user approval (mood constraint)
                    logger.info(f"[agentic-loop] Tool requires confirmation: {tool_name}")
                    confirm_item = GimoItem(
                        type="text",
                        content=f"[CONFIRMATION REQUIRED] {result_message}",
                        status="completed",
                        metadata={"requires_confirmation": True, "tool_data": result_data},
                    )
                    ConversationService.append_item(thread_id, orch_turn.id, confirm_item)

                    # Ask user via ask_user flow
                    final_response = f"⏸️ {result_message}. Approve to continue?"
                    finish_reason = "requires_confirmation"
                    break

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

    @staticmethod
    async def run_stream(
        thread_id: str,
        user_message: str,
        workspace_root: str,
        token: str = "system",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming variant of run() that yields SSE events as they happen.

        P2: Enhanced with mood-driven flow and meta-tools support.
        """
        # 1. Resolve orchestrator
        adapter, provider_id, model = _resolve_orchestrator_adapter()

        # 2. Get thread and mood profile (P2)
        thread = ConversationService.get_thread(thread_id)
        if not thread:
            yield {"event": "error", "data": {"message": f"Thread {thread_id} not found"}}
            return

        mood = thread.mood or "neutral"
        try:
            mood_profile = get_mood_profile(mood)
        except KeyError:
            logger.warning(f"Invalid mood '{mood}', using neutral")
            mood_profile = get_mood_profile("neutral")
            mood = "neutral"

        yield {"event": "session_start", "data": {
            "thread_id": thread_id,
            "provider": provider_id,
            "model": model,
            "mood": mood,
            "temperature": mood_profile.temperature,
            "max_turns": mood_profile.max_turns,
        }}

        # 3. Save user message
        user_turn = ConversationService.add_turn(thread_id, agent_id="user")
        if not user_turn:
            yield {"event": "error", "data": {"message": f"Thread {thread_id} not found after turn"}}
            return
        user_item = GimoItem(type="text", content=user_message, status="completed")
        ConversationService.append_item(thread_id, user_turn.id, user_item)

        # 4. Build system prompt with mood (P2)
        tree = _generate_workspace_tree(workspace_root)
        mood_prefix = mood_profile.prompt_prefix or ""
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            workspace_root=workspace_root,
            tree=tree,
            mood_prefix=mood_prefix
        )

        # 5. Build messages from thread history
        messages = _build_messages_from_thread(thread.turns, system_prompt)

        # 6. Setup executor with mood (P2)
        executor = ToolExecutor(workspace_root=workspace_root, token=token, mood=mood)

        # 7. Agentic loop (P2: mood-driven, streaming)
        total_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        all_tool_logs: List[Dict[str, Any]] = []
        final_response = ""
        iterations_used = 0
        finish_reason = "stop"
        max_turns = mood_profile.max_turns

        for iteration in range(max_turns):
            iterations_used = iteration + 1
            yield {"event": "iteration_start", "data": {"iteration": iterations_used, "mood": mood}}

            # Call LLM with mood temperature (P2)
            try:
                llm_result = await adapter.chat_with_tools(
                    messages=messages,
                    tools=CHAT_TOOLS,
                    temperature=mood_profile.temperature,
                )
            except Exception as exc:
                logger.error(f"LLM call failed on iteration {iteration}: {exc}")
                final_response = f"Error communicating with LLM: {exc}"
                yield {"event": "error", "data": {"message": final_response}}
                break

            # Accumulate usage
            usage = llm_result.get("usage", {})
            for key in total_usage:
                total_usage[key] += usage.get(key, 0)

            content = llm_result.get("content")
            tool_calls = llm_result.get("tool_calls", [])
            finish_reason = llm_result.get("finish_reason", "stop")

            # Emit text content if present
            if content:
                yield {"event": "text_delta", "data": {"content": content}}

            # No tool_calls -> final response
            if not tool_calls:
                final_response = content or ""
                break

            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": content, "tool_calls": tool_calls}
            messages.append(assistant_msg)

            orch_turn = ConversationService.add_turn(thread_id, agent_id="orchestrator")
            if not orch_turn:
                break

            if content:
                text_item = GimoItem(type="text", content=content, status="completed")
                ConversationService.append_item(thread_id, orch_turn.id, text_item)

            for tc in tool_calls[:MAX_TOOLS_PER_RESPONSE]:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                tool_call_id = tc.get("id", "")

                raw_args = func.get("arguments", "{}")
                try:
                    tool_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    tool_args = {}

                risk = get_tool_risk_level(tool_name)

                tc_item = GimoItem(
                    type="tool_call",
                    content=json.dumps(tool_args),
                    status="started",
                    metadata={"tool_name": tool_name, "tool_call_id": tool_call_id, "risk": risk},
                )
                ConversationService.append_item(thread_id, orch_turn.id, tc_item)

                # Emit tool_call_start event
                yield {"event": "tool_call_start", "data": {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "arguments": tool_args,
                    "risk": risk,
                }}

                # HITL gate for HIGH risk tools
                if risk == "HIGH":
                    yield {"event": "tool_approval_required", "data": {
                        "thread_id": thread_id,
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "risk": "HIGH",
                    }}

                    approved = await AgenticLoopService._request_approval(
                        thread_id, tool_call_id, tool_name, tool_args
                    )
                    if not approved:
                        denial_msg = f"Tool '{tool_name}' was denied by user (HITL)."
                        tr_item = GimoItem(
                            type="tool_result", content=denial_msg, status="error",
                            metadata={"tool_call_id": tool_call_id, "tool_name": tool_name, "duration": 0.0, "hitl": "denied"},
                        )
                        ConversationService.append_item(thread_id, orch_turn.id, tr_item)
                        messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": denial_msg})
                        all_tool_logs.append({
                            "name": tool_name, "arguments": tool_args,
                            "status": "denied", "message": denial_msg, "risk": risk, "duration": 0.0,
                        })
                        yield {"event": "tool_call_end", "data": {
                            "tool_call_id": tool_call_id, "tool_name": tool_name,
                            "status": "denied", "duration": 0.0, "risk": risk,
                        }}
                        continue

                # Execute tool
                start_time = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        executor.execute_tool_call(tool_name, tool_args),
                        timeout=TOOL_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    result = {"status": "error", "message": f"Tool '{tool_name}' timed out after {TOOL_TIMEOUT_SECONDS}s"}
                duration = time.monotonic() - start_time

                result_status = result.get("status", "error")
                result_message = result.get("message", "")
                result_data = result.get("data", {})

                # P2: Handle special statuses in streaming mode
                if result_status == "user_question":
                    logger.info(f"[agentic-loop-stream] User question triggered")
                    question_item = GimoItem(
                        type="text",
                        content=f"[QUESTION] {result_data.get('question', result_message)}",
                        status="completed",
                        metadata={"awaiting_user_response": True, "question_data": result_data},
                    )
                    ConversationService.append_item(thread_id, orch_turn.id, question_item)

                    yield {"event": "user_question", "data": {
                        "question": result_data.get("question", result_message),
                        "options": result_data.get("options", []),
                        "context": result_data.get("context", ""),
                    }}

                    final_response = f"⏸️ Waiting for your answer"
                    finish_reason = "user_question"
                    break

                if result_status == "plan_proposed":
                    logger.info(f"[agentic-loop-stream] Plan proposed")
                    thread.proposed_plan = result_data
                    ConversationService.save_thread(thread)

                    plan_item = GimoItem(
                        type="text",
                        content=f"[PLAN PROPOSED] {result_data.get('title', 'Plan')}",
                        status="completed",
                        metadata={"plan": result_data},
                    )
                    ConversationService.append_item(thread_id, orch_turn.id, plan_item)

                    yield {"event": "plan_proposed", "data": result_data}

                    final_response = f"⏸️ Plan proposed. Review to continue."
                    finish_reason = "plan_proposed"
                    break

                if result_status == "requires_confirmation":
                    logger.info(f"[agentic-loop-stream] Tool requires confirmation: {tool_name}")
                    confirm_item = GimoItem(
                        type="text",
                        content=f"[CONFIRMATION REQUIRED] {result_message}",
                        status="completed",
                        metadata={"requires_confirmation": True, "tool_data": result_data},
                    )
                    ConversationService.append_item(thread_id, orch_turn.id, confirm_item)

                    yield {"event": "confirmation_required", "data": {
                        "tool_name": tool_name,
                        "message": result_message,
                        "tool_data": result_data,
                    }}

                    final_response = f"⏸️ {result_message}"
                    finish_reason = "requires_confirmation"
                    break

                tool_result_content = result_message
                if result_data:
                    data_str = json.dumps(result_data, ensure_ascii=False)
                    if len(data_str) > 8000:
                        data_str = data_str[:8000] + "... (truncated)"
                    tool_result_content = f"{result_message}\n{data_str}"

                tr_item = GimoItem(
                    type="tool_result",
                    content=tool_result_content,
                    status="completed" if result_status == "success" else "error",
                    metadata={"tool_call_id": tool_call_id, "tool_name": tool_name, "duration": round(duration, 3)},
                )
                ConversationService.append_item(thread_id, orch_turn.id, tr_item)

                messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": tool_result_content})

                tool_log = {
                    "name": tool_name, "arguments": tool_args,
                    "status": result_status, "message": result_message,
                    "risk": risk, "duration": round(duration, 3),
                }
                all_tool_logs.append(tool_log)

                yield {"event": "tool_call_end", "data": {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "status": result_status,
                    "message": result_message[:200],
                    "duration": round(duration, 3),
                    "risk": risk,
                }}

        else:
            final_response = "(Reached maximum iterations. Stopping.)"

        # Save final response
        final_turn = ConversationService.add_turn(thread_id, agent_id="orchestrator")
        if final_turn and final_response:
            final_item = GimoItem(type="text", content=final_response, status="completed")
            ConversationService.append_item(thread_id, final_turn.id, final_item)

        # Calculate cost
        try:
            cost_usd = CostService.calculate_cost(
                model=model,
                input_tokens=total_usage.get("prompt_tokens", 0),
                output_tokens=total_usage.get("completion_tokens", 0),
            )
            total_usage["cost_usd"] = cost_usd
        except Exception:
            pass

        yield {"event": "done", "data": {
            "response": final_response,
            "tool_calls": all_tool_logs,
            "usage": total_usage,
            "turns_used": iterations_used,
            "finish_reason": finish_reason,
        }}

    # ── P2: Plan-Node Agentic Execution ───────────────────────────────────────

    @staticmethod
    async def run_node(
        workspace_root: str,
        node_prompt: str,
        mood: str = "executor",
        max_turns: int = 10,
        temperature: float | None = None,
        tools: List[Dict[str, Any]] | None = None,
        token: str = "system",
    ) -> AgenticResult:
        """Execute a mini agentic loop for a single plan node.

        P2: Unlike run(), this does NOT save to ConversationService. It's a
        standalone loop for CustomPlan node execution with tool support.
        """
        # Resolve orchestrator
        adapter, provider_id, model = _resolve_orchestrator_adapter()

        # Load mood profile
        try:
            mood_profile = get_mood_profile(mood)
        except KeyError:
            logger.warning(f"Invalid mood '{mood}', using executor")
            mood_profile = get_mood_profile("executor")
            mood = "executor"

        # Override temperature if provided
        if temperature is None:
            temperature = mood_profile.temperature

        # Use provided tools or default to CHAT_TOOLS
        if tools is None:
            tools = CHAT_TOOLS

        logger.info(f"[run_node] mood={mood}, temp={temperature}, max_turns={max_turns}")

        # Build system prompt
        tree = _generate_workspace_tree(workspace_root)
        mood_prefix = mood_profile.prompt_prefix or ""
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            workspace_root=workspace_root,
            tree=tree,
            mood_prefix=mood_prefix
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": node_prompt},
        ]

        # Setup executor
        executor = ToolExecutor(workspace_root=workspace_root, token=token, mood=mood)

        # Mini agentic loop
        total_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        all_tool_logs: List[Dict[str, Any]] = []
        final_response = ""
        iterations_used = 0
        finish_reason = "stop"

        for iteration in range(max_turns):
            iterations_used = iteration + 1

            try:
                llm_result = await adapter.chat_with_tools(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                )
            except Exception as exc:
                logger.error(f"[run_node] LLM call failed: {exc}")
                final_response = f"Error: {exc}"
                finish_reason = "error"
                break

            usage = llm_result.get("usage", {})
            for key in total_usage:
                total_usage[key] += usage.get(key, 0)

            content = llm_result.get("content")
            tool_calls = llm_result.get("tool_calls", [])
            finish_reason = llm_result.get("finish_reason", "stop")

            if not tool_calls:
                final_response = content or ""
                break

            # Process tool calls
            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": content, "tool_calls": tool_calls}
            messages.append(assistant_msg)

            for tc in tool_calls[:MAX_TOOLS_PER_RESPONSE]:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                tool_call_id = tc.get("id", "")

                raw_args = func.get("arguments", "{}")
                try:
                    tool_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    tool_args = {}

                risk = get_tool_risk_level(tool_name)

                # Execute tool
                start_time = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        executor.execute_tool_call(tool_name, tool_args),
                        timeout=TOOL_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    result = {"status": "error", "message": f"Tool '{tool_name}' timed out"}

                duration = time.monotonic() - start_time

                result_status = result.get("status", "error")
                result_message = result.get("message", "")
                result_data = result.get("data", {})

                # P2: Handle meta-tools in node context (simplified — no HITL)
                if result_status in ("user_question", "plan_proposed", "requires_confirmation"):
                    logger.warning(f"[run_node] Meta-tool '{tool_name}' called in node context (not supported). Skipping.")
                    result_message = f"[Node context] Tool '{tool_name}' requires interactive mode"
                    result_status = "error"

                tool_result_content = result_message
                if result_data:
                    data_str = json.dumps(result_data, ensure_ascii=False)
                    if len(data_str) > 8000:
                        data_str = data_str[:8000] + "... (truncated)"
                    tool_result_content = f"{result_message}\n{data_str}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": tool_result_content,
                })

                all_tool_logs.append({
                    "name": tool_name,
                    "arguments": tool_args,
                    "status": result_status,
                    "message": result_message,
                    "risk": risk,
                    "duration": round(duration, 3),
                })

        else:
            # Loop exhausted
            final_response = content or "(Node reached max iterations)"

        # Calculate cost
        try:
            cost_usd = CostService.calculate_cost(
                model=model,
                input_tokens=total_usage.get("prompt_tokens", 0),
                output_tokens=total_usage.get("completion_tokens", 0),
            )
            total_usage["cost_usd"] = cost_usd
        except Exception:
            pass

        return AgenticResult(
            response=final_response,
            tool_calls_log=all_tool_logs,
            usage=total_usage,
            turns_used=iterations_used,
            finish_reason=finish_reason,
        )
