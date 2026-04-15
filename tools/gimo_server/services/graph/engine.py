"""GraphEngine — MVP Graph Execution Engine.

Core execution loop that delegates to specialized mixins:
- BudgetGuardMixin: Budget checking and enforcement
- ContractValidatorMixin: Contract checks, rollback, human review
- AgentPatternsMixin: supervisor_workers, reviewer_loop, handoff
- NodeExecutorMixin: Node type dispatch (llm_call, tool_call, transform, etc.)
- CheckpointMixin: Checkpoint persistence, graph serialization, condition evaluation
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import inspect
import logging
import time
import uuid
from typing import Any, Dict, Optional

from tools.gimo_server.ops_models import (
    CostEvent,
    WorkflowCheckpoint,
    WorkflowGraph,
    WorkflowNode,
    WorkflowState,
)
from tools.gimo_server.models.agent_routing import TaskDescriptor
from tools.gimo_server.services.constraint_compiler_service import ConstraintCompilerService
from tools.gimo_server.services.model_router_service import ModelRouterService
from tools.gimo_server.services.profile_router_service import ProfileRouterService
from tools.gimo_server.services.observability_pkg.observability_service import ObservabilityService
from tools.gimo_server.services.storage_service import StorageService
from tools.gimo_server.services.providers.service import ProviderService
from tools.gimo_server.services.confidence_service import ConfidenceService
from tools.gimo_server.services.cascade_service import CascadeService

from .budget_guard import BudgetGuardMixin
from .contract_validator import ContractValidatorMixin
from .agent_patterns import AgentPatternsMixin
from .node_executor import NodeExecutorMixin
from .checkpoint_manager import CheckpointMixin

logger = logging.getLogger("orchestrator.services.graph_engine")


class GraphEngine(
    BudgetGuardMixin,
    ContractValidatorMixin,
    AgentPatternsMixin,
    NodeExecutorMixin,
    CheckpointMixin,
):
    """MVP Graph Execution Engine."""

    # Maximum nesting depth for sub_graph nodes to prevent infinite recursion.
    _MAX_SUB_GRAPH_DEPTH: int = 5

    def __init__(
        self,
        graph: WorkflowGraph,
        max_iterations: int = 100,
        storage: Optional[StorageService] = None,
        persist_checkpoints: bool = False,
        workflow_timeout_seconds: Optional[int] = None,
        confidence_service: Optional[ConfidenceService] = None,
        provider_service: Optional[ProviderService] = None,
        _sub_graph_depth: int = 0,
    ):
        self.graph = graph
        self.state = WorkflowState()
        self.max_iterations = max_iterations
        self.storage = storage
        self.persist_checkpoints = persist_checkpoints
        self.workflow_timeout_seconds = workflow_timeout_seconds
        self._confidence_service = confidence_service
        self._sub_graph_depth = _sub_graph_depth
        self._nodes_by_id = {node.id: node for node in self.graph.nodes}
        self._resume_from_node_id: Optional[str] = None
        self._execution_started_at: Optional[float] = None
        self._edges_from = {}
        for edge in self.graph.edges:
            self._edges_from.setdefault(edge.from_node, []).append(edge)
        self._model_router = ModelRouterService(storage=self.storage, confidence_service=self._confidence_service)
        self._provider_service = provider_service or ProviderService()
        self._cascade_service = CascadeService(self._provider_service, self._model_router)

    async def execute(self, initial_state: Optional[Dict[str, Any]] = None) -> WorkflowState:
        if initial_state:
            self.state.data.update(initial_state)
        if self._execution_started_at is None:
            self._execution_started_at = time.perf_counter()

        trace_id = str(self.state.data.get("trace_id") or uuid.uuid4().hex)
        self.state.data["trace_id"] = trace_id
        ObservabilityService.record_workflow_start(self.graph.id, trace_id)

        try:
            self.state.data.setdefault("step_logs", [])
            self.state.data.setdefault("budget_counters", {"steps": 0, "tokens": 0, "cost_usd": 0.0})

            if self.persist_checkpoints and self.storage:
                self.storage.save_workflow(self.graph.id, self._serialize_graph())

            if not self.graph.nodes:
                return self.state

            current_node_id = self._resume_from_node_id or self.graph.nodes[0].id
            self._resume_from_node_id = None
            iterations = 0

            while current_node_id and iterations < self.max_iterations:
                node = self._nodes_by_id[current_node_id]

                timeout_reason = self._check_workflow_timeout()
                if timeout_reason:
                    self.state.data["aborted_reason"] = timeout_reason
                    break

                try:
                    await self._ensure_budget_guard(node)
                except RuntimeError as e:
                    if "budget" in str(e).lower():
                        break
                    raise

                iterations += 1
                step_id = f"step_{iterations}"
                logger.info("%s: executing node=%s type=%s", step_id, node.id, node.type)
                started_at = time.perf_counter()

                try:
                    output = await self._run_node_with_retries(node)

                    if isinstance(output, dict):
                        self.state.data.update(output)

                    self._update_budget_counters(output)

                    if isinstance(output, dict) and output.get("pause_execution"):
                        self._resume_from_node_id = node.id
                        self.state.data["execution_paused"] = True
                        reason = output.get("pause_reason", "human_review_pending")
                        self.state.data["pause_reason"] = reason
                        self._append_step_log(
                            step_id=step_id,
                            node=node,
                            status="paused",
                            started_at=started_at,
                            output=output,
                        )

                        from tools.gimo_server.services.notification_service import NotificationService
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(NotificationService.publish("handover_required", {
                                "workflow_id": self.graph.id,
                                "node_id": node.id,
                                "reason": reason,
                                "context": output
                            }))
                        except Exception as ne:
                            logger.error("Failed to publish notification: %s", ne)

                        break

                    self.state.data["execution_paused"] = False

                    checkpoint = WorkflowCheckpoint(
                        node_id=node.id,
                        state=self.state.data.copy(),
                        output=output,
                        status="completed"
                    )
                    self.state.checkpoints.append(checkpoint)
                    self._persist_checkpoint(checkpoint)

                    self._append_step_log(
                        step_id=step_id,
                        node=node,
                        status="completed",
                        started_at=started_at,
                        output=output,
                    )

                    current_node_id = self._get_next_node(node.id, output)

                    budget_reason = self._check_budget_after_step()
                    if budget_reason:
                        self._handle_budget_exceeded(budget_reason)
                        break

                except Exception as e:
                    logger.error("Error executing node %s: %s", node.id, e)
                    if isinstance(e, TimeoutError):
                        error_text = "timed out"
                    else:
                        error_text = str(e) or e.__class__.__name__
                    checkpoint = WorkflowCheckpoint(
                        node_id=node.id,
                        state=self.state.data.copy(),
                        output=None,
                        status="failed"
                    )
                    self.state.checkpoints.append(checkpoint)
                    self._persist_checkpoint(checkpoint)
                    self._append_step_log(
                        step_id=step_id,
                        node=node,
                        status="failed",
                        started_at=started_at,
                        output={"error": error_text},
                    )
                    if not self.state.data.get("aborted_reason") and not self.state.data.get("pause_reason"):
                        self.state.data["aborted_reason"] = "node_failure"
                    break

            if current_node_id and iterations >= self.max_iterations:
                logger.warning("max_iterations reached (%s) at node=%s", self.max_iterations, current_node_id)
                self.state.data["aborted_reason"] = "max_iterations_exceeded"

        finally:
            workflow_status = "completed"
            if self.state.data.get("aborted_reason"):
                workflow_status = "failed"
            elif self.state.data.get("execution_paused"):
                workflow_status = "paused"

            ObservabilityService.record_workflow_end(
                self.graph.id,
                trace_id,
                status=workflow_status
            )

        return self.state

    async def _run_node_with_retries(self, node: WorkflowNode) -> Any:
        attempts = 0
        max_attempts = max(int(node.retries or 0) + 1, 1)
        base_backoff = float(node.config.get("retry_backoff_seconds", 0.0) or 0.0)
        last_error: Optional[Exception] = None

        while attempts < max_attempts:
            attempts += 1
            try:
                if node.timeout and int(node.timeout) > 0:
                    output = await asyncio.wait_for(self._run_node(node), timeout=int(node.timeout))
                else:
                    output = await self._run_node(node)

                if attempts > 1 and isinstance(output, dict):
                    output.setdefault("retry_attempts", attempts)
                return output
            except Exception as exc:
                last_error = exc
                if attempts >= max_attempts:
                    raise
                if base_backoff > 0:
                    await asyncio.sleep(base_backoff * (2 ** (attempts - 1)))

        raise RuntimeError(str(last_error) if last_error else f"Node failed without error: {node.id}")

    async def _run_node(self, node: WorkflowNode) -> Any:
        if node.type == "human_review":
            return await self._run_human_review(node)

        if node.type == "contract_check":
            return self._run_contract_check(node)

        if node.type == "agent_task":
            return await self._run_agent_task(node)

        if node.type == "llm_call":
             return await self._run_llm_call_with_cascade(node)

        return await self._call_execute_node(node)

    async def _run_llm_call_with_cascade(self, node: WorkflowNode) -> Any:
        from tools.gimo_server.services.ops_service import OpsService
        config = OpsService.get_config()

        economy = config.economy
        autonomy = economy.autonomy_level

        can_cascade = (
            economy.cascade.enabled and
            autonomy in ["guided", "autonomous"]
        )

        if not can_cascade:
             return await self._call_execute_node(node)

        prompt, context = self._prepare_llm_payload(node)

        result = await self._cascade_service.execute_with_cascade(
            prompt,
            context,
            economy.cascade,
            node_budget=node.config.get("budget"),
            current_state=self.state.data
        )

        self.state.data["last_cascade"] = result.model_dump()
        self.state.data.setdefault("cascade_trace", []).append({
            "node_id": node.id,
            "success": result.success,
            "attempts": len(result.cascade_chain)
        })

        output = result.final_output
        if isinstance(output, dict):
            output["cascade_total_input_tokens"] = result.total_input_tokens
            output["cascade_total_output_tokens"] = result.total_output_tokens
            output["cascade_total_tokens"] = result.total_tokens
            output["cascade_total_cost_usd"] = result.total_cost_usd
            output["cascade_level"] = len(result.cascade_chain) - 1
            output["cascade_success"] = result.success
            output["cascade_savings"] = result.savings

        return output

    async def _call_execute_node(self, node: WorkflowNode) -> Any:
        await self._ensure_budget_guard(node)

        execute_callable = self._execute_node
        if node.type in {"llm_call", "agent_task"}:
            # F7.3: Use ProfileRouterService for canonical routing
            # Build task descriptor from node config
            descriptor = TaskDescriptor(
                task_id=node.id,
                title=node.config.get("name") or node.config.get("label") or node.id,
                description=str(node.config.get("description", "")),
                task_type=str(node.config.get("task_type", "general")),
                task_semantic=str(node.config.get("task_semantic", "general")),
                complexity_band=str(node.config.get("complexity", "medium")),
                risk_band=str(node.config.get("risk_level", "low")),
            )

            # Build task context for constraint compilation
            task_context = {
                "cost_ceiling": node.config.get("cost_ceiling"),
                "binding_mode": "runtime",
                "budget_mode": node.config.get("budget_mode", "standard"),
            }

            # Get agent_preset from node config
            agent_preset = str(node.config.get("agent_preset", "executor"))

            # Compile constraints then route via canonical pipeline
            constraints = ConstraintCompilerService.compile_for_descriptor(descriptor, task_context=task_context)
            routing_decision = ProfileRouterService.route(
                descriptor=descriptor,
                constraints=constraints,
                requested_preset=agent_preset,
                requested_mood=str(node.config.get("mood") or "").strip() or None,
            )

            # Extract provider/model from routing_decision (v2.0 canonical fields)
            # Keep routing_summary for backward compat only
            routing_summary = routing_decision.summary

            # Store routing summary in node config for observability and executor
            if isinstance(node.config, dict):
                node.config["routing_decision_summary"] = routing_summary.model_dump()  # Backward compat
                node.config["selected_model"] = routing_decision.binding.model  # v2.0 canonical

            # Update state tracking (v2.0 canonical)
            self.state.data["model_router_last"] = {
                "node_id": node.id,
                "selected_model": routing_decision.binding.model,
                "reason": routing_decision.routing_reason,
                "provider_id": routing_decision.binding.provider,
                "agent_preset": routing_decision.profile.agent_preset,
                "execution_policy": routing_decision.profile.execution_policy,
            }
            self.state.data.setdefault("model_router_trace", []).append(self.state.data["model_router_last"])

        params = inspect.signature(execute_callable).parameters
        if len(params) >= 2:
            return await execute_callable(node, self.state.data)
        return await execute_callable(node)

    def _append_step_log(
        self,
        *,
        step_id: str,
        node: WorkflowNode,
        status: str,
        started_at: float,
        output: Any,
    ) -> None:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        log_entry = {
            "step_id": step_id,
            "node_id": node.id,
            "node_type": node.type,
            "status": status,
            "duration_ms": duration_ms,
            "agent_used": node.agent,
            "output": output,
        }
        self.state.data.setdefault("step_logs", []).append(log_entry)

        tokens_used = 0
        in_tokens = 0
        out_tokens = 0
        cost_usd = 0.0
        if isinstance(output, dict):
            in_tokens = int(output.get("cascade_total_input_tokens") or output.get("prompt_tokens", 0) or 0)
            out_tokens = int(output.get("cascade_total_output_tokens") or output.get("completion_tokens", 0) or 0)
            tokens_used = int(output.get("cascade_total_tokens") or output.get("tokens_used", 0) or (in_tokens + out_tokens))
            cost_usd = float(output.get("cascade_total_cost_usd") or output.get("cost_usd", 0.0) or 0.0)

        ObservabilityService.record_node_span(
            workflow_id=self.graph.id,
            trace_id=str(self.state.data.get("trace_id", "")),
            step_id=step_id,
            node_id=node.id,
            node_type=node.type,
            status=status,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
        )

        router_last = self.state.data.get("model_router_last", {})
        model_used = router_last.get("selected_model") or node.config.get("selected_model") or node.config.get("model") or "unknown"
        task_type = node.config.get("task_type", "default")

        if node.type in {"llm_call", "agent_task"}:
             trust_engine = getattr(self.storage, "trust_engine", None)
             if trust_engine:
                 conf_service = ConfidenceService(trust_engine)
                 dim_key = f"{task_type}|{model_used}"
                 confidence = conf_service.get_confidence_score(dim_key)
                 log_entry["confidence"] = confidence

        if self.storage and hasattr(self.storage, "cost") and (tokens_used > 0 or cost_usd > 0):
             try:
                 from tools.gimo_server.services.cost_service import CostService
                 provider = CostService.get_provider(model_used)

                 event = CostEvent(
                     id=uuid.uuid4().hex,
                     workflow_id=self.graph.id,
                     node_id=node.id,
                     model=str(model_used),
                     provider=provider,
                     task_type=str(task_type),
                     input_tokens=in_tokens,
                     output_tokens=out_tokens,
                     total_tokens=tokens_used,
                     cost_usd=cost_usd,
                     quality_score=float((output.get("quality_rating", {}) or {}).get("score", 0.0)) if isinstance(output, dict) else 0.0,
                     cascade_level=int(output.get("cascade_level", 0)) if isinstance(output, dict) else 0,
                     cache_hit=output.get("cache_hit", False) if isinstance(output, dict) else False,
                     duration_ms=duration_ms,
                     timestamp=datetime.now(timezone.utc)
                 )
                 self.storage.cost.save_cost_event(event)

             except Exception as e:
                 logger.warning("Failed to save cost event for node %s: %s", node.id, e)
