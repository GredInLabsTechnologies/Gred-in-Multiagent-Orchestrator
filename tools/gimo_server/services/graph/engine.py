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
from typing import Any, Dict, List, Optional

from tools.gimo_server.ops_models import (
    CostEvent,
    GraphCommand,
    is_graph_command,
    WorkflowCheckpoint,
    WorkflowGraph,
    WorkflowNode,
    WorkflowState,
)
from tools.gimo_server.services.model_router_service import ModelRouterService
from tools.gimo_server.services.observability_service import ObservabilityService
from tools.gimo_server.services.storage_service import StorageService
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.confidence_service import ConfidenceService
from tools.gimo_server.services.cascade_service import CascadeService

from .budget_guard import BudgetGuardMixin
from .contract_validator import ContractValidatorMixin
from .agent_patterns import AgentPatternsMixin
from .node_executor import NodeExecutorMixin
from .checkpoint_manager import CheckpointMixin
from .map_reduce import MapReduceMixin
from .state_manager import StateManager

# Sentinel: nodo siguiente no fue overrideado por un Command
_NO_COMMAND_OVERRIDE = object()

logger = logging.getLogger("orchestrator.services.graph_engine")


class GraphEngine(
    BudgetGuardMixin,
    ContractValidatorMixin,
    AgentPatternsMixin,
    NodeExecutorMixin,
    CheckpointMixin,
    MapReduceMixin,
):
    """MVP Graph Execution Engine."""

    def __init__(
        self,
        graph: WorkflowGraph,
        max_iterations: int = 100,
        storage: Optional[StorageService] = None,
        persist_checkpoints: bool = False,
        workflow_timeout_seconds: Optional[int] = None,
        confidence_service: Optional[ConfidenceService] = None,
        provider_service: Optional[ProviderService] = None,
    ):
        self.graph = graph
        self.state = WorkflowState()
        self.max_iterations = max_iterations
        self.storage = storage
        self.persist_checkpoints = persist_checkpoints
        self.workflow_timeout_seconds = workflow_timeout_seconds
        self._confidence_service = confidence_service
        self._nodes_by_id = {node.id: node for node in self.graph.nodes}
        self._resume_from_node_id: Optional[str] = None
        self._execution_started_at: Optional[float] = None
        self._edges_from = {}
        for edge in self.graph.edges:
            self._edges_from.setdefault(edge.from_node, []).append(edge)
        self._model_router = ModelRouterService(storage=self.storage, confidence_service=self._confidence_service)
        self._provider_service = provider_service or ProviderService()
        self._cascade_service = CascadeService(self._provider_service, self._model_router)
        self._state_manager = StateManager(
            reducers=self.graph.reducers,
            workflow_id=self.graph.id,
        )
        self._cycle_edges: set = self._detect_cycles()

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

                    # Fase 2: detectar GraphCommand
                    next_node_override = _NO_COMMAND_OVERRIDE
                    if is_graph_command(output):
                        effective_output, next_node_override = await self._handle_graph_command(
                            output, node.id
                        )
                        output = effective_output

                    if isinstance(output, dict):
                        self._apply_state_update(output)

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
                            logger.error(f"Failed to publish notification: {ne}")

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

                    if next_node_override is _NO_COMMAND_OVERRIDE:
                        current_node_id = self._get_next_node(node.id, output)
                    else:
                        current_node_id = next_node_override

                    budget_reason = self._check_budget_after_step()
                    if budget_reason:
                        self._handle_budget_exceeded(budget_reason)
                        break

                except Exception as e:
                    logger.error(f"Error executing node {node.id}: {e}")
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
            routing = await self._model_router.choose_model(node, self.state.data)
            self.state.data["model_router_last"] = {
                "node_id": node.id,
                "selected_model": routing.model,
                "reason": routing.reason,
                "provider_id": getattr(routing, "provider_id", ""),
                "hardware_state": getattr(routing, "hardware_state", "safe"),
                "tier": getattr(routing, "tier", 3),
            }
            self.state.data.setdefault("model_router_trace", []).append(self.state.data["model_router_last"])

            if isinstance(node.config, dict):
                node.config["selected_model"] = routing.model

        params = inspect.signature(execute_callable).parameters
        if len(params) >= 2:
            return await execute_callable(node, self.state.data)
        return await execute_callable(node)

    async def _handle_graph_command(
        self,
        command: GraphCommand,
        node_id: str,
    ):
        """Procesa un GraphCommand: aplica update, ejecuta sends, resuelve next node.

        Retorna (effective_output_dict, next_node_id_or_None).
        """
        effective_output = dict(command.update) if command.update else {}

        # Aplicar update atómico vía StateManager (antes de Send para que los
        # workers lo vean en su estado base)
        if command.update:
            self._state_manager.apply_update(self.state.data, command.update)

        # Fase 3: ejecutar Send (map-reduce) si hay acciones
        if command.send:
            await self._execute_send_actions(command.send, node_id)

        # GICS: registrar traza del command
        self._record_command_trace(command, node_id)

        # Resolver nodo siguiente
        if command.graph == "PARENT":
            # Escape de subgraph hacia el grafo padre
            self.state.data["_subgraph_escape"] = True
            return effective_output, None

        if command.goto is None:
            return effective_output, self._get_next_node(node_id, effective_output)

        if isinstance(command.goto, list):
            if len(command.goto) == 0:
                return effective_output, None
            if len(command.goto) == 1:
                return effective_output, command.goto[0]
            # Múltiples targets sin Send → error
            raise ValueError(
                f"Command.goto con múltiples targets {command.goto} requiere Send. "
                "Use command.send para fan-out."
            )

        return effective_output, command.goto

    def _record_command_trace(self, command: GraphCommand, node_id: str) -> None:
        gics = getattr(self, "_gics", None)
        if not gics:
            return
        key = f"ops:command_trace:{self.graph.id}"
        try:
            gics.put(key, {
                "node_id": node_id,
                "goto": command.goto,
                "has_update": bool(command.update),
                "has_send": bool(command.send),
                "graph": command.graph,
            })
        except Exception as e:
            logger.debug("GICS command_trace record failed: %s", e)

    # ── Fase 4: Ciclos declarativos ──────────────────────────

    def _detect_cycles(self) -> set:
        """DFS para identificar back-edges (aristas que forman ciclos).

        Retorna un set de edge_keys con formato 'from_node->to_node'.
        """
        visited: set = set()
        in_stack: set = set()
        cycle_edges: set = set()

        def dfs(node_id: str) -> None:
            visited.add(node_id)
            in_stack.add(node_id)
            for edge in self._edges_from.get(node_id, []):
                if edge.to_node not in visited:
                    dfs(edge.to_node)
                elif edge.to_node in in_stack:
                    cycle_edges.add(f"{edge.from_node}->{edge.to_node}")
            in_stack.discard(node_id)

        for node in self.graph.nodes:
            if node.id not in visited:
                dfs(node.id)

        return cycle_edges

    def _get_next_node(self, node_id: str, output: Any) -> Optional[str]:
        """Override de CheckpointMixin que añade soporte para ciclos declarativos.

        Para cada arista candidata:
        1. Si tiene break_condition y evalúa True → saltar (romper el ciclo)
        2. Si tiene max_iterations y el contador lo alcanzó → saltar
        3. Evaluación normal de condition (sin cambios)
        4. Al seguir una arista cíclica, incrementar contador y registrar GICS
        """
        edges = self._edges_from.get(node_id, [])
        if not edges:
            return None

        cycle_counters = self.state.data.setdefault("_cycle_counters", {})

        for edge in edges:
            edge_key = f"{edge.from_node}->{edge.to_node}"

            # 1. break_condition: si es True, no seguir esta arista
            if edge.break_condition:
                if self._evaluate_condition(edge.break_condition, output):
                    continue

            # 2. max_iterations: si el contador alcanzó el límite, no seguir
            if edge.max_iterations is not None:
                count = cycle_counters.get(edge_key, 0)
                if count >= edge.max_iterations:
                    continue

            # 3. condition normal
            if edge.condition:
                if not self._evaluate_condition(edge.condition, output):
                    continue

            # Seguir esta arista — si es cíclica, incrementar contador
            is_cycle = (
                edge_key in self._cycle_edges
                or edge.max_iterations is not None
                or edge.break_condition is not None
            )
            if is_cycle:
                cycle_counters[edge_key] = cycle_counters.get(edge_key, 0) + 1
                self._record_cycle_stats(edge_key, cycle_counters[edge_key])

            return edge.to_node

        return None

    def _record_cycle_stats(self, edge_key: str, count: int) -> None:
        gics = getattr(self, "_gics", None)
        if not gics:
            return
        gics_key = f"ops:cycle_stats:{self.graph.id}:{edge_key.replace('->', ':')}"
        try:
            gics.put(gics_key, {"count": count, "edge": edge_key})
        except Exception as e:
            logger.debug("GICS cycle_stats record failed: %s", e)

    def _apply_state_update(self, output: Dict[str, Any]) -> None:
        self._state_manager.apply_update(self.state.data, output)

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
