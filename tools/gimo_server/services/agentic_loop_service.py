"""Core agentic loop for GIMO conversations and plan-node execution."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List

from ..engine.moods import MoodProfile, get_mood_profile
from ..engine.tools.chat_tools_schema import CHAT_TOOLS, filter_tools_by_policy, get_tool_risk_level
from ..engine.tools.executor import ToolExecutor
from ..models.agent_routing import RoutingDecisionSummary, WorkflowPhase
from ..ops_models import GimoItem, GimoTurn
from ..providers.base import ProviderAdapter
from ..security.execution_proof import ExecutionProof, ExecutionProofChain
from .agent_catalog_service import AgentCatalogService
from .conversation_service import ConversationService
from .cost_service import CostService
from .execution_policy_service import ExecutionPolicyService
from .notification_service import NotificationService
from .provider_auth_service import ProviderAuthService
from .provider_service_adapter_registry import build_provider_adapter
from .provider_service_impl import ProviderService
from .constraint_compiler_service import ConstraintCompilerService
from .task_descriptor_service import TaskDescriptorService
from .workspace.workspace_contract import WorkspaceContract

logger = logging.getLogger("orchestrator.agentic_loop")

MAX_TURNS = 25
MAX_TOOLS_PER_RESPONSE = 10
TOOL_TIMEOUT_SECONDS = 30
HITL_APPROVAL_TIMEOUT = 300

SYSTEM_PROMPT_TEMPLATE = """You are GIMO, a governance-aware coding orchestrator.
You help users with software engineering tasks by reading, writing, and searching code.

Workspace: {workspace_root}
Task role: {task_role}
Workflow phase: {workflow_phase}
Project structure:
{tree}

Available tools: read_file, write_file, patch_file, search_replace, list_files, search_text, shell_exec, create_dir, ask_user, propose_plan, request_context, web_search

## Conversational Planning

For COMPLEX tasks (3+ files, new projects, structural refactors):
1. Ask clarifying questions with ask_user if anything is ambiguous
2. Investigate the workspace and research if needed (read_file, list_files, web_search)
3. Propose a plan with propose_plan and explain why you chose each agent preset and model
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

EventEmitter = Callable[[str, Dict[str, Any]], Awaitable[None]]


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


class ThreadExecutionBusyError(RuntimeError):
    """Raised when a conversational thread already has an active agentic loop."""


def _generate_workspace_tree(workspace_root: str, max_depth: int = 2, max_entries: int = 100) -> str:
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
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    for turn in thread_turns:
        if turn.agent_id in ("user", "User"):
            for item in turn.items:
                if item.type == "text" and item.content:
                    messages.append({"role": "user", "content": item.content})
        elif turn.agent_id == "orchestrator":
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
                    pending_tool_calls.append(
                        {
                            "id": tc_meta.get("tool_call_id", item.id),
                            "type": "function",
                            "function": {
                                "name": tc_meta.get("tool_name", ""),
                                "arguments": item.content,
                            },
                        }
                    )
                elif item.type == "tool_result":
                    tc_meta = item.metadata or {}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_meta.get("tool_call_id", item.id),
                            "content": item.content,
                        }
                    )

            if pending_tool_calls:
                messages.append({"role": "assistant", "content": None, "tool_calls": pending_tool_calls})

    return messages


def _resolve_orchestrator_adapter() -> tuple[ProviderAdapter, str, str, str]:
    """Returns (adapter, provider_id, model, canonical_provider_type)."""
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
    return adapter, provider_id, model, canonical_type


def _resolve_bound_adapter(
    provider_id: str,
    model: str,
    allow_orchestrator_fallback: bool = True,
) -> tuple[ProviderAdapter, str, str, str]:
    """Returns (adapter, provider_id, model, canonical_provider_type)."""
    cfg = ProviderService.get_config()
    if not cfg:
        raise RuntimeError("Provider config not found. Run gimo init or configure providers.")
    if provider_id in {"", "auto"}:
        if allow_orchestrator_fallback:
            return _resolve_orchestrator_adapter()
        # Plan node: intentar resolver via topology
        from .profile_binding_service import ProfileBindingService
        binding = ProfileBindingService.resolve_binding(binding_mode="plan_time")
        if binding.provider not in {"", "auto"}:
            return _resolve_bound_adapter(binding.provider, binding.model, True)
        return _resolve_orchestrator_adapter()  # ultimo recurso
    entry = cfg.providers.get(provider_id)
    if not entry:
        raise RuntimeError(f"Provider '{provider_id}' not found in providers")
    canonical_type = ProviderService.normalize_provider_type(entry.provider_type or entry.type)
    adapter = build_provider_adapter(
        entry=entry,
        canonical_type=canonical_type,
        resolve_secret=ProviderAuthService.resolve_secret,
    )
    resolved_model = model if model and model != "auto" else str(entry.model_id or entry.model or "")
    return adapter, provider_id, resolved_model, canonical_type


class AgenticLoopService:
    """Runs the agentic loop: LLM -> tool_calls -> execute -> repeat.
    
    **Authority of the conversational frontier loop.**
    """

    THREAD_LOCK_SCOPE = "thread_execution"
    THREAD_LOCK_TTL_SECONDS = 120
    THREAD_LOCK_HEARTBEAT_SECONDS = 30
    _pending_approvals: Dict[str, asyncio.Event] = {}
    _approval_results: Dict[str, bool] = {}
    _thread_execution_lock = threading.Lock()
    _active_thread_executions: Dict[str, str] = {}

    @staticmethod
    def _get_ops_service():
        try:
            from .ops_service import OpsService

            return OpsService
        except Exception:
            return None

    @classmethod
    def reserve_thread_execution(cls, thread_id: str) -> Dict[str, Any]:
        owner_id = f"thread_exec_{uuid.uuid4().hex[:16]}"
        ops_service = cls._get_ops_service()
        if ops_service is not None:
            ops_service.recover_stale_execution_lock(cls.THREAD_LOCK_SCOPE, thread_id)
            try:
                return ops_service.acquire_execution_lock(
                    cls.THREAD_LOCK_SCOPE,
                    thread_id,
                    owner_id,
                    ttl_seconds=cls.THREAD_LOCK_TTL_SECONDS,
                    metadata={"thread_id": thread_id},
                )
            except RuntimeError as exc:
                raise ThreadExecutionBusyError(str(exc)) from exc

        with cls._thread_execution_lock:
            active_owner = cls._active_thread_executions.get(thread_id)
            if active_owner and active_owner != owner_id:
                raise ThreadExecutionBusyError(f"Thread {thread_id} already has an active execution")
            cls._active_thread_executions[thread_id] = owner_id
        return {
            "lock_id": owner_id,
            "scope": cls.THREAD_LOCK_SCOPE,
            "resource_id": thread_id,
            "owner_id": owner_id,
            "backend": "memory",
        }

    @classmethod
    def release_thread_execution(cls, thread_id: str, owner_id: str | None = None) -> None:
        ops_service = cls._get_ops_service()
        if ops_service is not None:
            try:
                ops_service.release_execution_lock(cls.THREAD_LOCK_SCOPE, thread_id, owner_id or "")
            except Exception:
                logger.warning(
                    "Lock release via OpsService failed for %s (owner=%s) — forcing memory cleanup",
                    thread_id, owner_id, exc_info=True,
                )
        # Always clean up in-memory state regardless of OpsService result
        with cls._thread_execution_lock:
            active_owner = cls._active_thread_executions.get(thread_id)
            if active_owner and active_owner != owner_id:
                logger.warning(
                    "Lock owner mismatch on release: stored=%s, releasing=%s — releasing anyway",
                    active_owner, owner_id,
                )
            cls._active_thread_executions.pop(thread_id, None)

    @classmethod
    def heartbeat_thread_execution(cls, thread_id: str, owner_id: str) -> Dict[str, Any] | None:
        ops_service = cls._get_ops_service()
        if ops_service is not None:
            return ops_service.heartbeat_execution_lock(
                cls.THREAD_LOCK_SCOPE,
                thread_id,
                owner_id,
                ttl_seconds=cls.THREAD_LOCK_TTL_SECONDS,
            )
        with cls._thread_execution_lock:
            if cls._active_thread_executions.get(thread_id) != owner_id:
                raise RuntimeError(f"Thread {thread_id} lock held by another owner")
        return None

    @classmethod
    def _start_thread_execution_heartbeat(
        cls, thread_id: str, owner_id: str
    ) -> tuple[asyncio.Event, asyncio.Task[None], asyncio.Event]:
        stop_event = asyncio.Event()
        lock_lost = asyncio.Event()

        async def _heartbeat() -> None:
            while not stop_event.is_set():
                await asyncio.sleep(cls.THREAD_LOCK_HEARTBEAT_SECONDS)
                if stop_event.is_set():
                    break
                try:
                    cls.heartbeat_thread_execution(thread_id, owner_id)
                except Exception:
                    logger.warning("Heartbeat failed for %s — signaling lock_lost", thread_id, exc_info=True)
                    lock_lost.set()
                    break

        return stop_event, asyncio.create_task(_heartbeat()), lock_lost

    @staticmethod
    async def _stop_heartbeat(stop_event: asyncio.Event, task: asyncio.Task[None]) -> None:
        stop_event.set()
        task.cancel()
        try:
            await task
        except BaseException:
            pass

    @classmethod
    def submit_approval(cls, thread_id: str, tool_call_id: str, approved: bool) -> bool:
        key = f"{thread_id}:{tool_call_id}"
        event = cls._pending_approvals.get(key)
        if not event:
            return False
        cls._approval_results[key] = approved
        event.set()
        return True

    @classmethod
    async def _request_approval(
        cls, thread_id: str, tool_call_id: str, tool_name: str, tool_args: Dict[str, Any]
    ) -> bool:
        key = f"{thread_id}:{tool_call_id}"
        event = asyncio.Event()
        cls._pending_approvals[key] = event

        await NotificationService.publish(
            "tool_approval_required",
            {
                "thread_id": thread_id,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "arguments": tool_args,
                "risk": "HIGH",
                "critical": True,
            },
        )

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
    def _get_gics():
        try:
            from .ops_service import OpsService

            return getattr(OpsService, "_gics", None)
        except Exception:
            return None

    @staticmethod
    def _gics_fields(record: Any) -> Dict[str, Any]:
        if not isinstance(record, dict):
            return {}
        if isinstance(record.get("fields"), dict):
            return dict(record["fields"])
        return dict(record)

    @classmethod
    def _task_stats_key(cls, task_key: str, model: str) -> str:
        return f"ops:task:{task_key}:{model}"

    @classmethod
    def _predict_max_tokens(cls, task_key: str, model: str) -> int | None:
        gics = cls._get_gics()
        if not gics:
            return None
        try:
            fields = cls._gics_fields(gics.get(cls._task_stats_key(task_key, model)))
            samples = int(fields.get("samples", 0) or 0)
            avg_output = float(fields.get("avg_output_tokens", 0) or 0)
            if samples >= 5 and avg_output > 0:
                return max(1, int(avg_output * 1.3))
        except Exception:
            logger.debug("Unable to predict max_tokens for task=%s model=%s", task_key, model, exc_info=True)
        return None

    @classmethod
    def _record_completion_tokens(cls, task_key: str, model: str, usage: Dict[str, Any]) -> None:
        completion_tokens = int((usage or {}).get("completion_tokens", 0) or 0)
        if completion_tokens <= 0:
            return
        gics = cls._get_gics()
        if not gics:
            return
        key = cls._task_stats_key(task_key, model)
        try:
            fields = cls._gics_fields(gics.get(key))
            samples = int(fields.get("samples", 0) or 0)
            avg_output = float(fields.get("avg_output_tokens", 0) or 0)
            updated_samples = samples + 1
            rolling_avg = ((avg_output * samples) + completion_tokens) / max(1, updated_samples)
            gics.put(
                key,
                {
                    **fields,
                    "samples": updated_samples,
                    "avg_output_tokens": rolling_avg,
                    "last_used": time.time(),
                },
            )
        except Exception:
            logger.debug("Unable to update completion-token stats for task=%s model=%s", task_key, model, exc_info=True)

    @staticmethod
    def _calculate_usage_cost(model: str, usage: Dict[str, Any]) -> float:
        if not usage:
            return 0.0
        try:
            return float(
                CostService.calculate_cost(
                    model=model,
                    input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                    output_tokens=int(usage.get("completion_tokens", 0) or 0),
                )
            )
        except Exception:
            return 0.0

    @staticmethod
    def _parse_tool_arguments(raw_args: Any) -> Dict[str, Any]:
        try:
            parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            logger.warning("Malformed tool_call arguments (JSONDecodeError): %.200s",
                           raw_args if isinstance(raw_args, str) else type(raw_args).__name__)
            return {}

    @staticmethod
    def _build_tool_result_content(message: str, data: Dict[str, Any]) -> str:
        if not data:
            return message
        data_str = json.dumps(data, ensure_ascii=False)
        if len(data_str) > 8000:
            data_str = data_str[:8000] + "... (truncated)"
        return f"{message}\n{data_str}"

    @classmethod
    def _scan_execution_proof_records(cls, thread_id: str) -> tuple[List[Dict[str, Any]], bool]:
        gics = cls._get_gics()
        if not gics:
            return [], True
        try:
            rows = gics.scan(prefix=f"ops:proof:{thread_id}:")
            records: List[Dict[str, Any]] = []
            for row in rows:
                fields = cls._gics_fields(row)
                if fields:
                    records.append(fields)
            return records, True
        except Exception:
            logger.warning("Unable to scan proof chain for thread %s", thread_id, exc_info=True)
            return [], False

    @classmethod
    def _best_effort_sort_proof_records(cls, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def _sort_key(record: Dict[str, Any]) -> tuple[float, str]:
            try:
                timestamp = float(record.get("timestamp", 0) or 0)
            except Exception:
                timestamp = 0.0
            return timestamp, str(record.get("proof_id", ""))

        return sorted(records, key=_sort_key)

    @classmethod
    def _recover_appendable_execution_proof_chain(
        cls, thread_id: str, records: List[Dict[str, Any]]
    ) -> ExecutionProofChain:
        recovered_records: List[Dict[str, Any]] = []
        for record in records:
            try:
                recovered_records.append(ExecutionProof(**record).to_dict())
            except Exception:
                continue

        if not recovered_records:
            return ExecutionProofChain(thread_id)

        try:
            return ExecutionProofChain.from_records(thread_id, recovered_records)
        except Exception:
            logger.warning("Unable to recover appendable proof chain for thread %s", thread_id, exc_info=True)
            return ExecutionProofChain(thread_id)

    @classmethod
    def _load_execution_proof_chain(cls, thread_id: str, *, recover: bool = False) -> ExecutionProofChain | None:
        records, scanned_ok = cls._scan_execution_proof_records(thread_id)
        if not scanned_ok:
            return None
        if not records:
            return ExecutionProofChain(thread_id)
        try:
            return ExecutionProofChain.from_records(thread_id, records)
        except Exception:
            logger.warning("Unable to reconstruct proof chain for thread %s", thread_id, exc_info=True)
            if recover:
                return cls._recover_appendable_execution_proof_chain(thread_id, records)
            return None

    @classmethod
    def _persist_execution_proof(
        cls,
        *,
        thread_id: str,
        chain: ExecutionProofChain,
        tool_name: str,
        args: Dict[str, Any],
        result: Dict[str, Any],
        mood: str,
    ) -> None:
        gics = cls._get_gics()
        if not gics:
            return
        try:
            proof = chain.append(tool_name=tool_name, args=args, result=result, mood=mood, cost=0.0)
            gics.put(f"ops:proof:{thread_id}:{proof.proof_id}", proof.to_dict())
        except Exception:
            logger.debug("Unable to persist execution proof for thread %s", thread_id, exc_info=True)

    @classmethod
    def get_thread_proofs(cls, thread_id: str) -> Dict[str, Any]:
        records, scanned_ok = cls._scan_execution_proof_records(thread_id)
        if not scanned_ok:
            return {"thread_id": thread_id, "verified": False, "proofs": []}
        if not records:
            return {"thread_id": thread_id, "verified": True, "proofs": []}
        try:
            chain = ExecutionProofChain.from_records(thread_id, records)
            proofs = [proof.to_dict() for proof in chain.to_list()]
            return {"thread_id": thread_id, "verified": chain.verify(), "proofs": proofs}
        except Exception:
            return {
                "thread_id": thread_id,
                "verified": False,
                "proofs": cls._best_effort_sort_proof_records(records),
            }

    @staticmethod
    async def _noop_emit(_event: str, _data: Dict[str, Any]) -> None:
        return None

    @staticmethod
    def _resolve_mood_profile(mood: str | None, *, fallback_mood: str) -> tuple[str, MoodProfile]:
        candidate = mood or fallback_mood
        try:
            profile = get_mood_profile(candidate)
        except KeyError:
            logger.warning("Invalid mood '%s', using %s", candidate, fallback_mood)
            profile = get_mood_profile(fallback_mood)
        return profile.name, profile

    @classmethod
    def _resolve_thread_runtime_context(
        cls,
        thread: Any,
    ) -> tuple[str, MoodProfile, str, WorkflowPhase | str, str]:
        workflow_phase = getattr(thread, "workflow_phase", "intake") or "intake"
        explicit_policy = None
        metadata = getattr(thread, "metadata", {}) or {}
        explicit_policy_raw = metadata.get("execution_policy")
        if isinstance(explicit_policy_raw, str) and explicit_policy_raw.strip():
            try:
                explicit_policy = ExecutionPolicyService.canonical_policy_name(explicit_policy_raw.strip())
            except KeyError:
                logger.warning(
                    "Invalid execution policy '%s' on thread %s; using catalog-derived policy",
                    explicit_policy_raw,
                    getattr(thread, "id", "<unknown>"),
                )

        agent_preset = str(getattr(thread, "agent_preset", "") or "").strip() or None
        if getattr(thread, "_legacy_missing_agent_preset", False):
            agent_preset = None

        raw_mood = str(getattr(thread, "mood", "") or "").strip() or None
        try:
            profile = AgentCatalogService.resolve_profile(
                agent_preset=agent_preset,
                legacy_mood=None if agent_preset else raw_mood,
                workflow_phase=workflow_phase,
            )
        except KeyError:
            profile = AgentCatalogService.resolve_profile(
                legacy_mood=raw_mood or "neutral",
                workflow_phase=workflow_phase,
            )

        if explicit_policy:
            profile = profile.model_copy(update={"execution_policy": explicit_policy})

        normalized_mood, mood_profile = cls._resolve_mood_profile(
            raw_mood if agent_preset is None else profile.mood,
            fallback_mood=profile.mood,
        )
        return (
            normalized_mood,
            mood_profile,
            profile.task_role,
            profile.workflow_phase,
            profile.execution_policy,
        )

    @staticmethod
    def _build_system_prompt(
        workspace_root: str,
        mood_profile: MoodProfile,
        *,
        task_role: str = "orchestrator",
        workflow_phase: WorkflowPhase | str = "planning",
    ) -> str:
        tree = _generate_workspace_tree(workspace_root)
        # Inject workspace governance if available
        governance_block = ""
        try:
            if WorkspaceContract.is_initialized(workspace_root):
                contract = WorkspaceContract.verify(workspace_root)
                governance_block = contract.governance.prompt_constraints()
        except Exception as exc:
            logger.debug("Could not load workspace governance: %s", exc)
        base = SYSTEM_PROMPT_TEMPLATE.format(
            workspace_root=workspace_root,
            task_role=task_role,
            workflow_phase=workflow_phase,
            tree=tree,
            mood_prefix=mood_profile.prompt_prefix or "",
        )
        if governance_block:
            return f"{base}\n\n{governance_block}"
        return base

    @classmethod
    async def _run_loop(
        cls,
        *,
        adapter: ProviderAdapter,
        provider_id: str,
        model: str,
        workspace_root: str,
        token: str,
        mood: str,
        execution_policy: str | None = None,
        mood_profile: MoodProfile,
        messages: List[Dict[str, Any]],
        max_turns: int,
        temperature: float,
        tools: List[Dict[str, Any]],
        task_key: str,
        thread_id: str | None = None,
        thread: Any | None = None,
        emit: EventEmitter | None = None,
        persist_conversation: bool = False,
        allow_hitl: bool = False,
        force_hitl: bool = False,
        session_id: str | None = None,
    ) -> AgenticResult:
        emit_event = emit or cls._noop_emit
        if execution_policy:
            resolved_execution_policy = ExecutionPolicyService.canonical_policy_name(execution_policy)
        else:
            resolved_execution_policy = ExecutionPolicyService.policy_name_from_legacy_mood(mood)
        policy_profile = ExecutionPolicyService.get_policy(resolved_execution_policy)
        # Bootstrap workspace contract for governance + audit
        ws_contract = None
        try:
            ws_contract = WorkspaceContract.ensure(workspace_root)
        except Exception as exc:
            logger.debug("Workspace contract not available: %s", exc)
        executor = ToolExecutor(
            workspace_root=workspace_root,
            token=token,
            mood=mood,
            execution_policy=resolved_execution_policy,
            session_id=session_id,
            workspace_contract=ws_contract,
        )
        total_usage: Dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated": False}
        all_tool_logs: List[Dict[str, Any]] = []
        final_response = ""
        finish_reason = "stop"
        iterations_used = 0
        total_cost = 0.0
        total_budget = float(policy_profile.max_cost_per_turn_usd or 0.0) * max(1, max_turns)
        proof_chain = cls._load_execution_proof_chain(thread_id, recover=True) if thread_id else None
        last_content = ""
        last_tool_call_format = "none"

        await emit_event(
            "session_start",
            {
                "thread_id": thread_id,
                "provider": provider_id,
                "model": model,
                "mood": mood,
                "execution_policy": resolved_execution_policy,
                "temperature": temperature,
                "max_turns": max_turns,
            },
        )

        for iteration in range(max_turns):
            iterations_used = iteration + 1
            await emit_event("iteration_start", {
                "iteration": iterations_used,
                "mood": mood,
                "cumulative_cost": round(total_cost, 6),
            })

            predicted_max_tokens = cls._predict_max_tokens(task_key, model)
            try:
                llm_result = await adapter.chat_with_tools(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=predicted_max_tokens,
                )
            except Exception as exc:
                logger.error("LLM call failed on iteration %s: %s", iteration, exc)
                final_response = f"Error communicating with LLM: {exc}"
                finish_reason = "error"
                await emit_event("error", {"message": final_response})
                break

            usage = llm_result.get("usage", {}) or {}
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                total_usage[key] += int(usage.get(key, 0) or 0)
            # Propagate estimation flag: any estimated turn taints the whole loop's totals
            if usage.get("estimated"):
                total_usage["estimated"] = True

            cls._record_completion_tokens(task_key, model, usage)
            iteration_cost = cls._calculate_usage_cost(model, usage)
            total_cost += iteration_cost

            if iteration_cost > float(policy_profile.max_cost_per_turn_usd or 0.0):
                finish_reason = "turn_budget_exhausted"
                final_response = f"Turn budget exhausted for execution policy '{resolved_execution_policy}'."
                break
            if total_cost > total_budget:
                finish_reason = "budget_exhausted"
                final_response = f"Budget exhausted for execution policy '{resolved_execution_policy}'."
                break

            content = llm_result.get("content")
            tool_calls = list(llm_result.get("tool_calls", []) or [])
            finish_reason = llm_result.get("finish_reason", "stop")
            last_content = content or last_content
            last_tool_call_format = llm_result.get("tool_call_format", "none")

            if content:
                await emit_event("text_delta", {"content": content})

            if not content and not tool_calls and finish_reason == "stop":
                final_response = "[Hollow completion: LLM returned empty content and no tool calls]"
                finish_reason = "error"
                await emit_event("hollow_completion_error", {
                    "thread_id": thread_id,
                    "turn": iteration,
                    "model": model,
                })
                break

            if not tool_calls:
                final_response = content or ""
                break

            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            orch_turn = None
            if persist_conversation and thread_id:
                orch_turn = ConversationService.add_turn(thread_id, agent_id="orchestrator")
                if not orch_turn:
                    final_response = f"Thread {thread_id} not found while saving assistant turn"
                    finish_reason = "error"
                    await emit_event("error", {"message": final_response})
                    break
                if content:
                    ConversationService.append_item(
                        thread_id,
                        orch_turn.id,
                        GimoItem(type="text", content=content, status="completed"),
                    )

            stop_loop = False
            for tc in tool_calls[:MAX_TOOLS_PER_RESPONSE]:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                tool_call_id = tc.get("id", "")
                tool_args = cls._parse_tool_arguments(func.get("arguments", "{}"))
                risk = get_tool_risk_level(tool_name)

                if persist_conversation and thread_id and orch_turn:
                    ConversationService.append_item(
                        thread_id,
                        orch_turn.id,
                        GimoItem(
                            type="tool_call",
                            content=json.dumps(tool_args),
                            status="started",
                            metadata={"tool_name": tool_name, "tool_call_id": tool_call_id, "risk": risk},
                        ),
                    )

                await emit_event(
                    "tool_call_start",
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "risk": risk,
                    },
                )

                if allow_hitl and thread_id and (risk == "HIGH" or force_hitl):
                    await emit_event(
                        "tool_approval_required",
                        {
                            "thread_id": thread_id,
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "arguments": tool_args,
                            "risk": "HIGH",
                        },
                    )
                    approved = await cls._request_approval(thread_id, tool_call_id, tool_name, tool_args)
                    if not approved:
                        denial_msg = f"Tool '{tool_name}' was denied by user (HITL)."
                        if persist_conversation and thread_id and orch_turn:
                            ConversationService.append_item(
                                thread_id,
                                orch_turn.id,
                                GimoItem(
                                    type="tool_result",
                                    content=denial_msg,
                                    status="error",
                                    metadata={
                                        "tool_call_id": tool_call_id,
                                        "tool_name": tool_name,
                                        "duration": 0.0,
                                        "hitl": "denied",
                                    },
                                ),
                            )
                        messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": denial_msg})
                        all_tool_logs.append(
                            {
                                "name": tool_name,
                                "arguments": tool_args,
                                "status": "denied",
                                "message": denial_msg,
                                "risk": risk,
                                "duration": 0.0,
                            }
                        )
                        await emit_event(
                            "tool_call_end",
                            {
                                "tool_call_id": tool_call_id,
                                "tool_name": tool_name,
                                "status": "denied",
                                "duration": 0.0,
                                "risk": risk,
                                "iteration_cost": 0.0,
                                "cumulative_cost": round(total_cost, 6),
                            },
                        )
                        continue

                # Enforce execution policy permissions
                if resolved_execution_policy:
                    try:
                        policy = ExecutionPolicyService.get_policy(resolved_execution_policy)
                        # Check if tool is in allowed_tools
                        if policy.allowed_tools and tool_name not in policy.allowed_tools:
                            raise PermissionError(f"Tool '{tool_name}' not in allowed_tools for policy '{resolved_execution_policy}'")
                    except PermissionError as policy_err:
                        denial_msg = f"Tool '{tool_name}' denied by execution policy '{resolved_execution_policy}': {policy_err}"
                        logger.warning(denial_msg)
                        if persist_conversation and thread_id and orch_turn:
                            ConversationService.append_item(
                                thread_id,
                                orch_turn.id,
                                GimoItem(
                                    type="tool_result",
                                    content=denial_msg,
                                    status="error",
                                    metadata={
                                        "tool_call_id": tool_call_id,
                                        "tool_name": tool_name,
                                        "duration": 0.0,
                                        "policy_denied": resolved_execution_policy,
                                    },
                                ),
                            )
                        messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": denial_msg})
                        all_tool_logs.append(
                            {
                                "name": tool_name,
                                "arguments": tool_args,
                                "status": "policy_denied",
                                "message": denial_msg,
                                "risk": risk,
                                "duration": 0.0,
                            }
                        )
                        await emit_event(
                            "tool_call_end",
                            {
                                "tool_call_id": tool_call_id,
                                "tool_name": tool_name,
                                "status": "policy_denied",
                                "duration": 0.0,
                                "risk": risk,
                                "policy": resolved_execution_policy,
                                "iteration_cost": 0.0,
                                "cumulative_cost": round(total_cost, 6),
                            },
                        )
                        continue

                start_time = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        executor.execute_tool_call(tool_name, tool_args),
                        timeout=TOOL_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    result = {
                        "status": "error",
                        "message": f"Tool '{tool_name}' timed out after {TOOL_TIMEOUT_SECONDS}s",
                    }
                duration = round(time.monotonic() - start_time, 3)

                result_status = result.get("status", "error")
                result_message = result.get("message", "")
                result_data = result.get("data", {}) or {}

                if thread_id and proof_chain and result_status == "success":
                    cls._persist_execution_proof(
                        thread_id=thread_id,
                        chain=proof_chain,
                        tool_name=tool_name,
                        args=tool_args,
                        result=result,
                        mood=mood,
                    )

                if thread_id is None and result_status in {"user_question", "plan_proposed", "requires_confirmation"}:
                    result_status = "error"
                    result_message = f"[Node context] Tool '{tool_name}' requires interactive mode"
                    result_data = {}

                if result_status == "user_question":
                    question = result_data.get("question", result_message)
                    if persist_conversation and thread_id and orch_turn:
                        ConversationService.append_item(
                            thread_id,
                            orch_turn.id,
                            GimoItem(
                                type="text",
                                content=f"[QUESTION] {question}",
                                status="completed",
                                metadata={"awaiting_user_response": True, "question_data": result_data},
                            ),
                        )
                    await emit_event(
                        "user_question",
                        {
                            "question": question,
                            "options": result_data.get("options", []),
                            "context": result_data.get("context", ""),
                        },
                    )
                    final_response = f"Waiting for your answer to: {question}"
                    finish_reason = "user_question"
                    stop_loop = True
                    break

                if result_status == "plan_proposed":
                    try:
                        canonical_plan = TaskDescriptorService.canonicalize_plan_data(result_data)
                    except Exception as exc:
                        final_response = f"Invalid proposed plan: {exc}"
                        finish_reason = "error"
                        await emit_event("error", {"message": final_response})
                        stop_loop = True
                        break
                    if thread_id:
                        def _store_proposed_plan(current: Any) -> bool:
                            current.proposed_plan = canonical_plan
                            current.workflow_phase = "awaiting_approval"
                            return True

                        updated = ConversationService.mutate_thread(thread_id, _store_proposed_plan)
                        if updated is None:
                            final_response = f"Thread {thread_id} not found while saving proposed plan"
                            finish_reason = "error"
                            await emit_event("error", {"message": final_response})
                            stop_loop = True
                            break
                        thread = ConversationService.get_thread(thread_id) or thread
                    if persist_conversation and thread_id and orch_turn:
                        ConversationService.append_item(
                            thread_id,
                            orch_turn.id,
                            GimoItem(
                                type="text",
                                content=f"[PLAN PROPOSED] {canonical_plan.get('title', 'Execution Plan')}",
                                status="completed",
                                metadata={"plan": canonical_plan},
                            ),
                        )
                    try:
                        await NotificationService.publish("plan_proposed", {"thread_id": thread_id, "plan": canonical_plan})
                    except Exception:
                        pass
                    await emit_event("plan_proposed", canonical_plan)
                    if canonical_plan:
                        final_response = "Plan proposed. Please review and approve to continue."
                        finish_reason = "plan_proposed"
                    else:
                        final_response = "Plan proposal failed: no plan data was generated."
                        finish_reason = "error"
                    stop_loop = True
                    break

                if result_status == "requires_confirmation":
                    if persist_conversation and thread_id and orch_turn:
                        ConversationService.append_item(
                            thread_id,
                            orch_turn.id,
                            GimoItem(
                                type="text",
                                content=f"[CONFIRMATION REQUIRED] {result_message}",
                                status="completed",
                                metadata={"requires_confirmation": True, "tool_data": result_data},
                            ),
                        )
                    await emit_event(
                        "confirmation_required",
                        {
                            "tool_name": tool_name,
                            "message": result_message,
                            "tool_data": result_data,
                        },
                    )
                    final_response = result_message
                    finish_reason = "requires_confirmation"
                    stop_loop = True
                    break

                if result_status == "context_request_pending":
                    if persist_conversation and thread_id and orch_turn:
                        ConversationService.append_item(
                            thread_id,
                            orch_turn.id,
                            GimoItem(
                                type="text",
                                content=f"[CONTEXT REQUEST] {result_message}",
                                status="completed",
                                metadata={"context_request": result_data},
                            ),
                        )
                    await emit_event("context_request_pending", result_data)
                    final_response = f"Execution paused: {result_message}"
                    finish_reason = "context_request_pending"
                    stop_loop = True
                    break


                tool_result_content = cls._build_tool_result_content(result_message, result_data)
                messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": tool_result_content})

                if persist_conversation and thread_id and orch_turn:
                    ConversationService.append_item(
                        thread_id,
                        orch_turn.id,
                        GimoItem(
                            type="tool_result",
                            content=tool_result_content,
                            status="completed" if result_status == "success" else "error",
                            metadata={
                                "tool_call_id": tool_call_id,
                                "tool_name": tool_name,
                                "duration": duration,
                            },
                        ),
                    )

                tool_log = ToolCallLog(
                    name=tool_name,
                    arguments=tool_args,
                    result_status=result_status,
                    result_message=result_message,
                    risk_level=risk,
                    duration_seconds=duration,
                )
                all_tool_logs.append(
                    {
                        "name": tool_log.name,
                        "arguments": tool_log.arguments,
                        "status": tool_log.result_status,
                        "message": tool_log.result_message,
                        "risk": tool_log.risk_level,
                        "duration": tool_log.duration_seconds,
                    }
                )

                await emit_event(
                    "tool_call_end",
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "status": result_status,
                        "message": result_message[:200],
                        "duration": duration,
                        "risk": risk,
                        "iteration_cost": round(iteration_cost, 6),
                        "cumulative_cost": round(total_cost, 6),
                    },
                )

            if stop_loop:
                break

        else:
            final_response = last_content or "(Reached maximum iterations. Stopping.)"

        total_usage["cost_usd"] = total_cost
        total_usage["cost_estimated"] = bool(total_usage.get("estimated"))

        # U4: Single telemetry sink — writes to metrics, audit log, and thread metadata.
        try:
            from .observability import ObservabilityService
            ObservabilityService.record_llm_usage(
                thread_id=thread_id,
                model=model or "unknown",
                prompt_tokens=total_usage.get("prompt_tokens", 0),
                completion_tokens=total_usage.get("completion_tokens", 0),
                cost_usd=total_cost,
                tools_executed=len(all_tool_logs),
                tool_call_format=last_tool_call_format or "none",
                estimated=bool(total_usage.get("estimated")),
            )
        except Exception:
            logger.debug("record_llm_usage failed", exc_info=True)

        # Wire 3: Response Honesty Gate — detect semantic mismatch between
        # tool results and the LLM's text response.  If every tool call failed
        # and the response doesn't mention the failure, override with an honest
        # summary so the user is never misled.
        if all_tool_logs and finish_reason not in ("error", "tool_error", "user_question"):
            _failed = [t for t in all_tool_logs if t.get("status") in ("error", "policy_denied", "denied")]
            _succeeded = [t for t in all_tool_logs if t.get("status") == "success"]
            if _failed and not _succeeded:
                _failure_words = {"fail", "error", "denied", "could not", "unable", "cannot"}
                _response_lower = (final_response or "").lower()
                if not any(w in _response_lower for w in _failure_words):
                    tool_errors = "; ".join(
                        f"{t['name']}: {t.get('message', t.get('status', 'failed'))}"
                        for t in _failed[:5]
                    )
                    final_response = f"All tool calls failed: {tool_errors}"
                    finish_reason = "tool_error"

        if persist_conversation and thread_id and final_response:
            final_turn = ConversationService.add_turn(thread_id, agent_id="orchestrator")
            if final_turn:
                ConversationService.append_item(
                    thread_id,
                    final_turn.id,
                    GimoItem(type="text", content=final_response, status="completed"),
                )

        result = AgenticResult(
            response=final_response,
            tool_calls_log=all_tool_logs,
            usage=total_usage,
            turns_used=iterations_used,
            finish_reason=finish_reason,
        )
        await emit_event(
            "done",
            {
                "response": result.response,
                "tool_calls": result.tool_calls_log,
                "usage": result.usage,
                "turns_used": result.turns_used,
                "finish_reason": result.finish_reason,
            },
        )
        return result

    @classmethod
    async def _run_reserved(
        cls,
        thread_id: str,
        user_message: str,
        workspace_root: str,
        token: str = "system",
        session_id: str | None = None,
    ) -> AgenticResult:
        adapter, provider_id, model, canonical_type = _resolve_orchestrator_adapter()
        thread = ConversationService.get_thread(thread_id)
        if not thread:
            raise RuntimeError(f"Thread {thread_id} not found")

        mood, mood_profile, task_role, workflow_phase, execution_policy = cls._resolve_thread_runtime_context(thread)

        # Wire 2: Dynamic trust-gated authority — GICS + TrustEngine constrain policy
        execution_policy, _trust_hitl = ConstraintCompilerService.apply_trust_authority(
            execution_policy,
            model_id=model,
            provider_type=canonical_type,
            workspace_root=workspace_root,
        )

        user_turn = ConversationService.add_turn(thread_id, agent_id="user")
        if not user_turn:
            raise RuntimeError(f"Thread {thread_id} not found after adding turn")
        ConversationService.append_item(
            thread_id,
            user_turn.id,
            GimoItem(type="text", content=user_message, status="completed"),
        )

        thread = ConversationService.get_thread(thread_id)
        if not thread:
            raise RuntimeError(f"Thread {thread_id} not found after saving user message")

        system_prompt = AgenticLoopService._build_system_prompt(
            workspace_root,
            mood_profile,
            task_role=task_role,
            workflow_phase=workflow_phase,
        )
        messages = _build_messages_from_thread(thread.turns, system_prompt)

        # Wire 4: Schema-time tool filtering — LLM only sees tools the policy allows
        try:
            policy_obj = ExecutionPolicyService.get_policy(execution_policy) if execution_policy else None
        except KeyError:
            logger.error("FAIL-CLOSED: Unknown execution policy %r — aborting tool binding", execution_policy)
            raise RuntimeError(f"Unknown execution policy: {execution_policy!r}")
        effective_tools = filter_tools_by_policy(CHAT_TOOLS, policy_obj.allowed_tools if policy_obj else None)

        return await AgenticLoopService._run_loop(
            adapter=adapter,
            provider_id=provider_id,
            model=model,
            workspace_root=workspace_root,
            token=token,
            mood=mood,
            execution_policy=execution_policy,
            mood_profile=mood_profile,
            messages=messages,
            max_turns=mood_profile.max_turns,
            temperature=mood_profile.temperature,
            tools=effective_tools,
            task_key="agentic_chat",
            thread_id=thread_id,
            thread=thread,
            persist_conversation=True,
            allow_hitl=True,
            force_hitl=_trust_hitl,
            session_id=session_id,
        )

    @classmethod
    async def run(
        cls,
        thread_id: str,
        user_message: str,
        workspace_root: str,
        token: str = "system",
        session_id: str | None = None,
    ) -> AgenticResult:
        reservation = cls.reserve_thread_execution(thread_id)
        owner_id = str(reservation.get("owner_id") or "")
        stop_event, heartbeat_task, _lock_lost = cls._start_thread_execution_heartbeat(thread_id, owner_id)
        try:
            return await cls._run_reserved(
                thread_id=thread_id,
                user_message=user_message,
                workspace_root=workspace_root,
                token=token,
                session_id=session_id,
            )
        finally:
            try:
                await cls._stop_heartbeat(stop_event, heartbeat_task)
            except Exception:
                logger.exception("Heartbeat stop failed for thread %s", thread_id)
            try:
                cls.release_thread_execution(thread_id, owner_id)
            except Exception:
                logger.exception("Lock release failed for thread %s", thread_id)

    @classmethod
    async def _run_stream_reserved(
        cls,
        thread_id: str,
        user_message: str,
        workspace_root: str,
        token: str = "system",
        session_id: str | None = None,
        lock_lost: asyncio.Event | None = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        adapter, provider_id, model, canonical_type = _resolve_orchestrator_adapter()
        thread = ConversationService.get_thread(thread_id)
        if not thread:
            yield {"event": "error", "data": {"message": f"Thread {thread_id} not found"}}
            return

        mood, mood_profile, task_role, workflow_phase, execution_policy = cls._resolve_thread_runtime_context(thread)

        # Wire 2: Dynamic trust-gated authority — GICS + TrustEngine constrain policy
        execution_policy, _trust_hitl = ConstraintCompilerService.apply_trust_authority(
            execution_policy,
            model_id=model,
            provider_type=canonical_type,
            workspace_root=workspace_root,
        )

        user_turn = ConversationService.add_turn(thread_id, agent_id="user")
        if not user_turn:
            yield {"event": "error", "data": {"message": f"Thread {thread_id} not found after turn"}}
            return
        ConversationService.append_item(
            thread_id,
            user_turn.id,
            GimoItem(type="text", content=user_message, status="completed"),
        )

        thread = ConversationService.get_thread(thread_id)
        if not thread:
            yield {"event": "error", "data": {"message": f"Thread {thread_id} not found after saving user message"}}
            return

        system_prompt = AgenticLoopService._build_system_prompt(
            workspace_root,
            mood_profile,
            task_role=task_role,
            workflow_phase=workflow_phase,
        )
        messages = _build_messages_from_thread(thread.turns, system_prompt)

        # Wire 4: Schema-time tool filtering
        try:
            policy_obj = ExecutionPolicyService.get_policy(execution_policy) if execution_policy else None
        except KeyError:
            logger.error("FAIL-CLOSED: Unknown execution policy %r — aborting tool binding", execution_policy)
            raise RuntimeError(f"Unknown execution policy: {execution_policy!r}")
        effective_tools = filter_tools_by_policy(CHAT_TOOLS, policy_obj.allowed_tools if policy_obj else None)

        queue: asyncio.Queue[Dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: str, data: Dict[str, Any]) -> None:
            await queue.put({"event": event, "data": data})

        async def runner() -> None:
            try:
                await AgenticLoopService._run_loop(
                    adapter=adapter,
                    provider_id=provider_id,
                    model=model,
                    workspace_root=workspace_root,
                    token=token,
                    mood=mood,
                    execution_policy=execution_policy,
                    mood_profile=mood_profile,
                    messages=messages,
                    max_turns=mood_profile.max_turns,
                    temperature=mood_profile.temperature,
                    tools=effective_tools,
                    task_key="agentic_stream",
                    thread_id=thread_id,
                    thread=thread,
                    emit=emit,
                    persist_conversation=True,
                    allow_hitl=True,
                    force_hitl=_trust_hitl,
                    session_id=session_id,
                )
            except Exception as exc:
                logger.exception("Streaming agentic loop failed")
                await queue.put({"event": "error", "data": {"message": f"Internal streaming error: {exc}"}})
            finally:
                await queue.put(None)

        task = asyncio.create_task(runner())
        try:
            while True:
                if lock_lost is not None and lock_lost.is_set():
                    yield {"event": "error", "data": {"message": "Execution lock lost — aborting stream"}}
                    task.cancel()
                    break
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            await asyncio.gather(task, return_exceptions=True)

    @classmethod
    async def run_stream(
        cls,
        thread_id: str,
        user_message: str,
        workspace_root: str,
        token: str = "system",
        session_id: str | None = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        reservation = cls.reserve_thread_execution(thread_id)
        owner_id = str(reservation.get("owner_id") or "")
        stop_event, heartbeat_task, lock_lost = cls._start_thread_execution_heartbeat(thread_id, owner_id)
        try:
            async for event in cls._run_stream_reserved(
                thread_id=thread_id,
                user_message=user_message,
                workspace_root=workspace_root,
                token=token,
                session_id=session_id,
                lock_lost=lock_lost,
            ):
                yield event
        finally:
            try:
                await cls._stop_heartbeat(stop_event, heartbeat_task)
            except Exception:
                logger.exception("Heartbeat stop failed for thread %s", thread_id)
            try:
                cls.release_thread_execution(thread_id, owner_id)
            except Exception:
                logger.exception("Lock release failed for thread %s", thread_id)

    @classmethod
    async def resume_session(
        cls,
        session_id: str,
        workspace_root: str,
        token: str = "system",
        emit: EventEmitter | None = None,
    ) -> AgenticResult:
        """Resumes a paused execution after context requests are resolved.
        
        This method is the canonical entry point for Phase 5B resume logic.
        """
        from .context_request_service import ContextRequestService
        resolved_list = ContextRequestService.get_resolved_requests(session_id)
        if not resolved_list:
            return AgenticResult(response="No resolved requests found for this session.", finish_reason="error")

        thread_id = session_id  # In multi-surface App, session_id is used as thread_id
        thread = ConversationService.get_thread(thread_id)
        if not thread:
            return AgenticResult(response=f"Thread {thread_id} not found.", finish_reason="error")
        runtime_context = cls._resolve_thread_runtime_context(thread)

        # Mark thread as executing
        try:
            reservation = cls.reserve_thread_execution(thread_id)
            owner_id = str(reservation.get("owner_id") or "")
        except ThreadExecutionBusyError:
            return AgenticResult(response="Session is already being resumed elsewhere.", finish_reason="error")

        stop_event, heartbeat_task, _lock_lost = cls._start_thread_execution_heartbeat(thread_id, owner_id)

        try:
            # Inject resolved contexts as TOOL RESULTS
            turn = ConversationService.add_turn(thread_id, agent_id="system")
            if not turn:
                 return AgenticResult(response="Failed to add recovery turn", finish_reason="error")
                 
            for req in resolved_list:
                call_id = req.get("metadata", {}).get("call_id", f"call_{req['id'][:8]}")
                content = f"[CONTEXT RESOLVED]: {req.get('result', 'No information provided.')}"
                if req.get("payload"):
                    content += f"\nData: {json.dumps(req['payload'], indent=2)}"
                
                ConversationService.append_item(
                    thread_id, turn.id,
                    GimoItem(
                        type="tool_result",
                        content=content,
                        status="completed",
                        metadata={"call_id": call_id, "tool_name": "request_context"}
                    )
                )
                # Archive so it's only used once
                ContextRequestService.update_request_status(session_id, req["id"], "archived")

            # Reload thread to get merged messages for the LLM
            thread = ConversationService.get_thread(thread_id)
            if not thread:
                return AgenticResult(response=f"Thread {thread_id} not found after recovery write.", finish_reason="error")
            mood, mood_profile, task_role, workflow_phase, execution_policy = runtime_context

            adapter, provider_id, model, canonical_type = _resolve_orchestrator_adapter()

            # Wire 2: Dynamic trust-gated authority
            execution_policy, _trust_hitl = ConstraintCompilerService.apply_trust_authority(
                execution_policy,
                model_id=model,
                provider_type=canonical_type,
                workspace_root=workspace_root,
            )

            system_prompt = cls._build_system_prompt(
                workspace_root,
                mood_profile,
                task_role=task_role,
                workflow_phase=workflow_phase,
            )
            messages = _build_messages_from_thread(thread.turns, system_prompt)

            # Wire 4: Schema-time tool filtering
            policy_obj = ExecutionPolicyService.get_policy(execution_policy) if execution_policy else None
            effective_tools = filter_tools_by_policy(CHAT_TOOLS, policy_obj.allowed_tools if policy_obj else None)

            return await cls._run_loop(
                adapter=adapter,
                provider_id=provider_id,
                model=model,
                workspace_root=workspace_root,
                token=token,
                mood=mood,
                execution_policy=execution_policy,
                mood_profile=mood_profile,
                messages=messages,
                max_turns=10,
                temperature=mood_profile.temperature,
                tools=effective_tools,
                task_key="resume",
                thread_id=thread_id,
                thread=thread,
                emit=emit,
                persist_conversation=True,
                allow_hitl=True,
                force_hitl=_trust_hitl,
                session_id=session_id,
            )
        finally:
            try:
                await cls._stop_heartbeat(stop_event, heartbeat_task)
            except Exception:
                logger.exception("Heartbeat stop failed for thread %s", thread_id)
            try:
                cls.release_thread_execution(thread_id, owner_id)
            except Exception:
                logger.exception("Lock release failed for thread %s", thread_id)

    @staticmethod
    async def run_node(
        workspace_root: str,
        node_prompt: str,
        mood: str = "executor",
        execution_policy: str | None = None,
        provider: str = "auto",
        model: str = "auto",
        task_role: str = "executor",
        workflow_phase: WorkflowPhase | str = "executing",
        max_turns: int = 10,
        temperature: float | None = None,
        tools: List[Dict[str, Any]] | None = None,
        token: str = "system",
        routing_summary: RoutingDecisionSummary | None = None,
    ) -> AgenticResult:
        # Si routing_summary está presente, extraer valores de allí
        if routing_summary:
            mood = routing_summary.mood
            execution_policy = routing_summary.execution_policy
            provider = routing_summary.provider
            model = routing_summary.model
            task_role = routing_summary.task_role
            workflow_phase = routing_summary.workflow_phase
            allow_fallback = False
        else:
            allow_fallback = True

        adapter, provider_id, resolved_model, _canonical_type = _resolve_bound_adapter(provider, model, allow_fallback)
        try:
            mood_profile = get_mood_profile(mood)
        except KeyError:
            logger.warning("Invalid mood '%s', using executor", mood)
            mood = "executor"
            mood_profile = get_mood_profile(mood)

        if execution_policy:
            resolved_policy = ExecutionPolicyService.canonical_policy_name(execution_policy)
        else:
            resolved_policy = ExecutionPolicyService.policy_name_from_legacy_mood(mood)
        resolved_temperature = mood_profile.temperature if temperature is None else temperature
        system_prompt = AgenticLoopService._build_system_prompt(
            workspace_root,
            mood_profile,
            task_role=task_role,
            workflow_phase=workflow_phase,
        )
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": node_prompt},
        ]
        return await AgenticLoopService._run_loop(
            adapter=adapter,
            provider_id=provider_id,
            model=resolved_model,
            workspace_root=workspace_root,
            token=token,
            mood=mood,
            execution_policy=resolved_policy,
            mood_profile=mood_profile,
            messages=messages,
            max_turns=max_turns,
            temperature=resolved_temperature,
            tools=tools or CHAT_TOOLS,
            task_key="plan_node",
            persist_conversation=False,
            allow_hitl=False,
        )
