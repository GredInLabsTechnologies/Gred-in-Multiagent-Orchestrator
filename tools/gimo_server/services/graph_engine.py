from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import inspect
import logging
from pathlib import Path
import time
import uuid
from typing import Any, Dict, List, Optional

from ..ops_models import (
    ContractCheck,
    WorkflowCheckpoint, 
    WorkflowContract,
    WorkflowEdge, 
    WorkflowGraph, 
    WorkflowNode, 
    WorkflowState
)
from .model_router_service import ModelRouterService
from .observability_service import ObservabilityService
from .storage_service import StorageService
from .provider_service import ProviderService
from .tool_registry_service import ToolRegistryService
from .cost_service import CostService
from .confidence_service import ConfidenceService
from .cascade_service import CascadeService
from ..adapters.mcp_client import McpClient

logger = logging.getLogger("orchestrator.services.graph_engine")


class GraphEngine:
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

    async def execute(self, initial_state: Optional[Dict[str, Any]] = None) -> WorkflowState:
        if initial_state:
            self.state.data.update(initial_state)
        if self._execution_started_at is None:
            self._execution_started_at = time.perf_counter()

        trace_id = str(self.state.data.get("trace_id") or uuid.uuid4().hex)
        self.state.data["trace_id"] = trace_id
        ObservabilityService.record_workflow_start(self.graph.id, trace_id)

        try:
            # Structured execution trace (MVP) stored in workflow state
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

                # Budget Check (Guarded)
                try:
                    await self._ensure_budget_guard(node)
                except RuntimeError as e:
                    if "budget" in str(e).lower():
                        # Already handled by _handle_budget_exceeded inside guard
                        break
                    raise

                iterations += 1
                step_id = f"step_{iterations}"
                logger.info("%s: executing node=%s type=%s", step_id, node.id, node.type)
                started_at = time.perf_counter()
                
                try:
                    output = await self._run_node_with_retries(node)

                    # Every node can mutate state by returning a dict
                    if isinstance(output, dict):
                        self.state.data.update(output)

                    self._update_budget_counters(output)

                    if isinstance(output, dict) and output.get("pause_execution"):
                        self._resume_from_node_id = node.id
                        self.state.data["execution_paused"] = True
                        self.state.data["pause_reason"] = output.get("pause_reason", "human_review_pending")
                        self._append_step_log(
                            step_id=step_id,
                            node=node,
                            status="paused",
                            started_at=started_at,
                            output=output,
                        )
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

                    # Determine next node
                    current_node_id = self._get_next_node(node.id, output)

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
                    # Preserves more specific reasons (like budget_exceeded or pause) if already set
                    if not self.state.data.get("aborted_reason") and not self.state.data.get("pause_reason"):
                        self.state.data["aborted_reason"] = "node_failure"
                    break

            if current_node_id and iterations >= self.max_iterations:
                logger.warning("max_iterations reached (%s) at node=%s", self.max_iterations, current_node_id)
                self.state.data["aborted_reason"] = "max_iterations_exceeded"

        finally:
            workflow_status = "completed"
            if self.state.data.get("aborted_reason"):
                workflow_status = "failed" # or "aborted"
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
        from .ops_service import OpsService
        config = OpsService.get_config()
        
        economy = config.economy
        autonomy = economy.autonomy_level
        
        # 1. Check if cascading is allowed
        can_cascade = (
            economy.cascade.enabled and 
            autonomy in ["guided", "autonomous"]
        )
        
        if not can_cascade:
             return await self._call_execute_node(node)
             
        # 2. Prepare Rendered Data
        prompt, context = self._prepare_llm_payload(node)
        
        # 3. Execute with cascade
        result = await self._cascade_service.execute_with_cascade(
            prompt,
            context,
            economy.cascade,
            node_budget=node.config.get("budget"),
            current_state=self.state.data
        )
        
        # 3. Update state with cascade trace
        self.state.data["last_cascade"] = result.model_dump()
        self.state.data.setdefault("cascade_trace", []).append({
            "node_id": node_id if 'node_id' in locals() else node.id,
            "success": result.success,
            "attempts": len(result.cascade_chain)
        })
        
        # 4. Return merged output with accumulated metrics
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
        
        """Run node and support both legacy and new execution signatures.

        Supported execution callables:
        - _execute_node(node)
        - _execute_node(node, state)
        """
        execute_callable = self._execute_node
        if node.type in {"llm_call", "agent_task"}:
            routing = await self._model_router.choose_model(node, self.state.data)
            self.state.data["model_router_last"] = {
                "node_id": node.id,
                "selected_model": routing.model,
                "reason": routing.reason,
            }
            self.state.data.setdefault("model_router_trace", []).append(self.state.data["model_router_last"])

            if isinstance(node.config, dict):
                node.config["selected_model"] = routing.model

        params = inspect.signature(execute_callable).parameters
        if len(params) >= 2:
            return await execute_callable(node, self.state.data)
        return await execute_callable(node)

    async def _check_proactive_confidence(self, node: WorkflowNode) -> Optional[Dict[str, Any]]:
        """Evaluates proactive confidence before task execution."""
        if self.state.data.get(f"approved_{node.id}"):
            logger.info("Skipping proactive confidence check for node %s (already approved)", node.id)
            return None

        if not self._confidence_service:
            return None

        task_description = node.config.get("description", node.config.get("task", ""))
        if not task_description:
            return None

        projection = self.state.data.get("node_confidence", {}).get(node.id)
        if not projection:
            try:
                projection = await self._confidence_service.project_confidence(
                    description=task_description,
                    context=self.state.data
                )
                self.state.data.setdefault("node_confidence", {})[node.id] = projection
            except Exception as e:
                logger.error("Proactive confidence projection failed for node %s: %s", node.id, e)
                return None # Fallback: let execution continue without doubt check

        if projection["score"] < 0.7:
            logger.warning("Agent Doubt detected: confidence=%s for node=%s", projection["score"], node.id)
            return {
                "pause_execution": True,
                "pause_reason": "agent_doubt",
                "doubt_analysis": projection["analysis"],
                "doubt_questions": projection["questions"],
                "confidence_score": projection["score"],
            }
        return None

    async def _run_agent_task(self, node: WorkflowNode) -> Dict[str, Any]:
        # 1. Trust Proyectado: EVALUACIÓN PROACTIVA
        doubt_response = await self._check_proactive_confidence(node)
        if doubt_response:
            return doubt_response

        pattern = str(node.config.get("pattern", "single")).strip().lower()

        if pattern == "supervisor_workers":
            workers = node.config.get("workers") or []
            fail_policy = str(node.config.get("fail_policy", "fail_fast") or "fail_fast").strip().lower()
            parallel = bool(node.config.get("parallel", False))
            max_parallel_workers = int(node.config.get("max_parallel_workers", len(workers) or 1) or 1)
            max_parallel_workers = max(1, max_parallel_workers)

            worker_results: Dict[str, Any] = {}

            async def _run_one_worker(idx: int, worker: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
                worker_id = str(worker.get("id") or f"worker_{idx + 1}")
                payload = {
                    "task": worker.get("task"),
                    "shared_context": dict(self.state.data),
                    "role": "worker",
                    "worker_id": worker_id,
                }
                worker_output = await self._run_agent_child(node, child_suffix=worker_id, payload=payload)
                return worker_id, worker_output

            if parallel and len(workers) > 1:
                semaphore = asyncio.Semaphore(max_parallel_workers)

                async def _run_bounded(idx: int, worker: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
                    async with semaphore:
                        return await _run_one_worker(idx, worker)

                if fail_policy == "collect_partial":
                    raw_results = await asyncio.gather(
                        *[_run_bounded(i, w) for i, w in enumerate(workers)],
                        return_exceptions=True,
                    )
                    worker_errors: Dict[str, str] = {}
                    for idx, item in enumerate(raw_results):
                        worker_id = str((workers[idx] or {}).get("id") or f"worker_{idx + 1}")
                        if isinstance(item, Exception):
                            worker_errors[worker_id] = str(item)
                            continue
                        wid, output = item
                        worker_results[wid] = output
                    return {
                        "pattern": "supervisor_workers",
                        "parallel": True,
                        "max_parallel_workers": max_parallel_workers,
                        "fail_policy": fail_policy,
                        "worker_results": worker_results,
                        "worker_errors": worker_errors,
                        "partial_success": len(worker_errors) > 0,
                    }

                # Default: fail_fast
                paired_results = await asyncio.gather(*[_run_bounded(i, w) for i, w in enumerate(workers)])
                for worker_id, output in paired_results:
                    worker_results[worker_id] = output
            else:
                for idx, worker in enumerate(workers):
                    worker_id = str(worker.get("id") or f"worker_{idx + 1}")
                    payload = {
                        "task": worker.get("task"),
                        "shared_context": dict(self.state.data),
                        "role": "worker",
                        "worker_id": worker_id,
                    }
                    if fail_policy == "collect_partial":
                        try:
                            worker_output = await self._run_agent_child(node, child_suffix=worker_id, payload=payload)
                            worker_results[worker_id] = worker_output
                        except Exception as exc:
                            worker_results.setdefault("_errors", {})[worker_id] = str(exc)
                        continue

                    worker_output = await self._run_agent_child(node, child_suffix=worker_id, payload=payload)
                    worker_results[worker_id] = worker_output

                if fail_policy == "collect_partial":
                    worker_errors = worker_results.pop("_errors", {})
                    return {
                        "pattern": "supervisor_workers",
                        "parallel": False,
                        "max_parallel_workers": 1,
                        "fail_policy": fail_policy,
                        "worker_results": worker_results,
                        "worker_errors": worker_errors,
                        "partial_success": len(worker_errors) > 0,
                    }

            return {
                "pattern": "supervisor_workers",
                "parallel": parallel,
                "max_parallel_workers": max_parallel_workers if parallel else 1,
                "fail_policy": fail_policy,
                "worker_results": worker_results,
            }

        if pattern == "reviewer_loop":
            max_rounds = max(int(node.config.get("max_rounds", 3) or 3), 1)
            candidate: Any = None
            feedback: Optional[str] = None
            reviews: List[Dict[str, Any]] = []

            for round_idx in range(1, max_rounds + 1):
                gen_output = await self._run_agent_child(
                    node,
                    child_suffix=f"generator_r{round_idx}",
                    payload={
                        "role": "generator",
                        "round": round_idx,
                        "candidate": candidate,
                        "feedback": feedback,
                    },
                )
                candidate = gen_output.get("candidate", gen_output)

                review_output = await self._run_agent_child(
                    node,
                    child_suffix=f"reviewer_r{round_idx}",
                    payload={
                        "role": "reviewer",
                        "round": round_idx,
                        "candidate": candidate,
                    },
                )
                approved = bool(review_output.get("approved", False))
                feedback = review_output.get("feedback")
                reviews.append(
                    {
                        "round": round_idx,
                        "approved": approved,
                        "feedback": feedback,
                    }
                )
                if approved:
                    return {
                        "pattern": "reviewer_loop",
                        "approved": True,
                        "rounds": round_idx,
                        "candidate": candidate,
                        "reviews": reviews,
                    }

            return {
                "pattern": "reviewer_loop",
                "approved": False,
                "rounds": max_rounds,
                "candidate": candidate,
                "reviews": reviews,
            }

        if pattern == "handoff":
            context_keys = node.config.get("context_keys") or []
            curated_context = {
                str(k): self.state.data.get(str(k))
                for k in context_keys
            }
            source_node_id = f"{node.id}__source"
            target_node_id = f"{node.id}__target"
            source_output = await self._run_agent_child(
                node,
                child_suffix="source",
                payload={
                    "role": "source",
                    "handoff_context": curated_context,
                },
            )
            target_output = await self._run_agent_child(
                node,
                child_suffix="target",
                payload={
                    "role": "target",
                    "handoff_context": curated_context,
                    "source_output": source_output,
                },
            )

            now_iso = datetime.now(timezone.utc).isoformat()
            handoff_package = {
                "source_node": source_node_id,
                "target_node": target_node_id,
                "timestamp": now_iso,
                "context_keys": [str(k) for k in context_keys],
                "handoff_context": curated_context,
                "summary": str(source_output.get("summary") or "handoff_completed"),
            }

            ObservabilityService.record_handoff_event(
                workflow_id=self.graph.id,
                trace_id=str(self.state.data.get("trace_id", "")),
                source_node=source_node_id,
                target_node=target_node_id,
                summary=handoff_package["summary"],
                timestamp=now_iso,
            )

            return {
                "pattern": "handoff",
                "handoff_package": handoff_package,
                "handoff_context": curated_context,
                "source_output": source_output,
                "target_output": target_output,
            }

        # default agent_task behaves as a single executable node
        output = await self._call_execute_node(node)
        if isinstance(output, dict):
            output.setdefault("pattern", "single")
        return output

    async def _run_agent_child(self, parent_node: WorkflowNode, *, child_suffix: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        child_node = WorkflowNode(
            id=f"{parent_node.id}__{child_suffix}",
            type="agent_task",
            config=payload,
            agent=parent_node.agent,
            timeout=parent_node.timeout,
            retries=0,
        )
        result = await self._call_execute_node(child_node)
        return result if isinstance(result, dict) else {"result": result}

    def _run_contract_check(self, node: WorkflowNode) -> Dict[str, Any]:
        """Execute contract checks in pre/post mode.

        Expected node.config:
        {
          "phase": "pre" | "post",
          "contract": { ... WorkflowContract-compatible ... }
        }
        """
        raw_contract = node.config.get("contract", node.config)
        contract = WorkflowContract.model_validate(raw_contract)
        phase = str(node.config.get("phase", "pre")).lower()
        checks = contract.pre_conditions if phase == "pre" else contract.post_conditions

        failed: List[Dict[str, Any]] = []
        for check in checks:
            passed = self._evaluate_contract_check(check)
            if not passed:
                failed.append({"type": check.type, "params": check.params})

        output = {
            "contract_phase": phase,
            "checks_total": len(checks),
            "checks_failed": failed,
            "contract_passed": len(failed) == 0,
            "blast_radius": contract.blast_radius,
        }

        if failed and phase == "post":
            rollback_result = self._run_rollback(contract.rollback)
            output["rollback_executed"] = rollback_result
            self.state.data["contract_failure"] = output
            raise RuntimeError(f"Post-contract checks failed: {failed}")

        if failed:
            self.state.data["contract_failure"] = output
            raise RuntimeError(f"Pre-contract checks failed: {failed}")

        self.state.data["last_contract_check"] = output
        return output

    async def _run_human_review(self, node: WorkflowNode) -> Dict[str, Any]:
        """Interactive HITL node.

        Uses state.data["human_reviews"][node.id] as operator/admin decision payload.
        Supported decision values:
        - approve
        - reject
        - edit_state
        - takeover
        - fork
        """
        reviews = self.state.data.setdefault("human_reviews", {})
        annotations = self.state.data.setdefault("human_annotations", [])
        decision_payload = reviews.get(node.id)

        timeout_seconds = int(node.config.get("timeout_seconds", 0) or 0)
        default_action = str(node.config.get("default_action", "block"))
        now = datetime.now(timezone.utc)
        pending_key = "human_review_pending"
        pending = dict(self.state.data.get(pending_key) or {})

        if not decision_payload:
            pending_started_at = pending.get("started_at")
            started_dt = self._parse_iso_ts(pending_started_at)
            if pending.get("node_id") != node.id or not started_dt:
                started_dt = now
                pending = {
                    "node_id": node.id,
                    "started_at": started_dt.isoformat(),
                    "timeout_seconds": timeout_seconds,
                    "default_action": default_action,
                }
                self.state.data[pending_key] = pending

            if timeout_seconds > 0 and (now - started_dt).total_seconds() >= timeout_seconds:
                if default_action == "approve":
                    self.state.data.pop(pending_key, None)
                    return {
                        "human_review": "auto_approved_timeout",
                        "human_review_node": node.id,
                    }
                raise RuntimeError(f"Human review timeout at node {node.id}; default_action={default_action}")

            return {
                "pause_execution": True,
                "pause_reason": "human_review_pending",
                "human_review_node": node.id,
                "timeout_seconds": timeout_seconds,
                "default_action": default_action,
            }

        decision = str(decision_payload.get("decision", "")).lower().strip()
        edited_state = decision_payload.get("edited_state") or {}
        annotation = decision_payload.get("annotation")
        if annotation:
            annotations.append(
                {
                    "node_id": node.id,
                    "timestamp": now.isoformat(),
                    "note": str(annotation),
                }
            )

        self.state.data.pop(pending_key, None)

        if decision == "approve":
            return {
                "human_review": "approved",
                "human_review_node": node.id,
            }

        if decision == "reject":
            raise RuntimeError(f"Human review rejected at node {node.id}")

        if decision in {"edit", "edit_state"}:
            if isinstance(edited_state, dict):
                self.state.data.update(edited_state)
            return {
                "human_review": "edited",
                "human_review_node": node.id,
                "edited_keys": sorted(list(edited_state.keys())) if isinstance(edited_state, dict) else [],
            }

        if decision == "takeover":
            if isinstance(edited_state, dict):
                self.state.data.update(edited_state)
            return {
                "human_review": "takeover",
                "human_review_node": node.id,
                "takeover": True,
            }

        if decision == "fork":
            branches = node.config.get("fork_options") or []
            selected_branch = decision_payload.get("selected_branch")
            if not isinstance(branches, list) or not branches:
                raise RuntimeError(f"Fork requested at node {node.id} but no branch selected")

            async def _run_branch(idx: int, branch: Any) -> Dict[str, Any]:
                await asyncio.sleep(0)
                if isinstance(branch, dict):
                    branch_id = str(branch.get("id") or branch.get("name") or f"branch_{idx + 1}")
                    return {
                        "branch_id": branch_id,
                        "state_patch": dict(branch.get("state_patch") or {}),
                        "output": branch.get("output"),
                    }

                branch_id = str(branch)
                return {
                    "branch_id": branch_id,
                    "state_patch": {},
                    "output": None,
                }

            branch_results = await asyncio.gather(*[_run_branch(i, b) for i, b in enumerate(branches)])
            by_id = {item["branch_id"]: item for item in branch_results}

            if selected_branch is None:
                selected_branch = branch_results[0]["branch_id"]

            selected_branch = str(selected_branch)
            selected_payload = by_id.get(selected_branch)
            if selected_payload is None:
                raise RuntimeError(f"Fork requested at node {node.id} but selected branch is invalid: {selected_branch}")

            state_patch = selected_payload.get("state_patch")
            if isinstance(state_patch, dict) and state_patch:
                self.state.data.update(state_patch)

            return {
                "human_review": "fork_selected",
                "human_review_node": node.id,
                "selected_branch": selected_branch,
                "fork_results": branch_results,
            }

        raise RuntimeError(f"Unsupported human review decision at node {node.id}: {decision}")

    def _evaluate_contract_check(self, check: ContractCheck) -> bool:
        check_type = check.type
        params = check.params

        if check_type == "file_exists":
            path = params.get("path")
            return bool(path and Path(path).exists())

        if check_type == "function_exists":
            func_name = params.get("function_name")
            content = params.get("content")
            if content is None and params.get("path"):
                try:
                    content = Path(params["path"]).read_text(encoding="utf-8")
                except Exception:
                    return False
            if not func_name or not isinstance(content, str):
                return False
            return f"def {func_name}(" in content

        if check_type == "tests_pass":
            key = params.get("state_key", "tests_passed")
            return bool(self.state.data.get(key, False))

        if check_type == "no_new_vulnerabilities":
            key = params.get("state_key", "new_vulnerabilities")
            return int(self.state.data.get(key, 0) or 0) == 0

        if check_type == "custom":
            key = params.get("state_key")
            expected = params.get("equals", True)
            if key is None:
                return False
            return self.state.data.get(key) == expected

        return False

    def _run_rollback(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        executed: List[Dict[str, Any]] = []
        for action in actions:
            action_type = action.get("type")
            if action_type == "set_state":
                key = action.get("key")
                if key is not None:
                    self.state.data[key] = action.get("value")
                    executed.append({"type": action_type, "key": key})
            elif action_type == "remove_state":
                key = action.get("key")
                if key in self.state.data:
                    self.state.data.pop(key, None)
                    executed.append({"type": action_type, "key": key})

        self.state.data["rollback_actions"] = executed
        return {"count": len(executed), "actions": executed}

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
            # Use cascade totals if they exist, otherwise the single call metrics
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

        # Infer model and task for tracing/persistence
        router_last = self.state.data.get("model_router_last", {})
        model_used = router_last.get("selected_model") or node.config.get("selected_model") or node.config.get("model") or "unknown"
        task_type = node.config.get("task_type", "default")

        # Token Mastery: Trace the confidence score for the node
        if node.type in {"llm_call", "agent_task"}:
             trust_engine = getattr(self.storage, "trust_engine", None)
             if trust_engine:
                 conf_service = ConfidenceService(trust_engine)
                 dim_key = f"{task_type}|{model_used}"
                 confidence = conf_service.get_confidence_score(dim_key)
                 log_entry["confidence"] = confidence

        # Token Mastery: Persist Cost Event
        if self.storage and hasattr(self.storage, "cost") and (tokens_used > 0 or cost_usd > 0):
             from ..ops_models import CostEvent
             try:
                 from .cost_service import CostService
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

    def _get_budget(self) -> Dict[str, Any]:
        runtime_budget = self.state.data.get("budget")
        if isinstance(runtime_budget, dict):
            return runtime_budget
        schema_budget = self.graph.state_schema.get("budget", {}) if isinstance(self.graph.state_schema, dict) else {}
        return schema_budget if isinstance(schema_budget, dict) else {}

    def _update_budget_counters(self, output: Any) -> None:
        counters = self.state.data.setdefault("budget_counters", {"steps": 0, "tokens": 0, "cost_usd": 0.0})
        counters["steps"] = int(counters.get("steps", 0)) + 1
        if isinstance(output, dict):
            # Prefer cascade totals to capture all attempts
            tokens = output.get("cascade_total_tokens") or output.get("tokens_used", 0)
            cost = output.get("cascade_total_cost_usd") or output.get("cost_usd", 0.0)
            counters["tokens"] = int(counters.get("tokens", 0)) + int(tokens or 0)
            counters["cost_usd"] = float(counters.get("cost_usd", 0.0)) + float(cost or 0.0)

    def _check_workflow_timeout(self) -> Optional[str]:
        if not self.workflow_timeout_seconds or self.workflow_timeout_seconds <= 0:
            return None
        if self._execution_started_at is None:
            return None
        elapsed = time.perf_counter() - self._execution_started_at
        if elapsed > self.workflow_timeout_seconds:
            return "workflow_timeout_exceeded"
        return None

    async def _check_budget_before_step(self, node: Optional[WorkflowNode] = None) -> Optional[str]:
        budget = self._get_budget()
        counters = self.state.data.get("budget_counters", {})
        max_steps = budget.get("max_steps")
        if isinstance(max_steps, int) and max_steps >= 0:
            if int(counters.get("steps", 0)) >= max_steps:
                return "budget_max_steps_exceeded"

        # Provider Budget Check (pre-step enforcement)
        if node and node.type in {"llm_call", "agent_task"} and self._model_router:
             provider_reason = await self._model_router.check_provider_budget(node, self.state.data)
             if provider_reason:
                 return provider_reason

        # Global Budget Check
        try:
            from .ops_service import OpsService
            config = OpsService.get_config()
            if config.economy and config.economy.global_budget_usd is not None:
                if self.storage and hasattr(self.storage, "cost"):
                    # user's global budget typically implies "monthly" or "current billing cycle"
                    # failing that, we stick to 30 days rolling window
                    total_spend = self.storage.cost.get_total_spend(days=30)
                    if total_spend >= config.economy.global_budget_usd:
                        return f"global_budget_exceeded: ${total_spend:.2f} >= ${config.economy.global_budget_usd:.2f}"
        except ImportError:
            pass

        return None

    async def _ensure_budget_guard(self, node: WorkflowNode) -> None:
        """Centralized guard to check budget and update state/abort if needed."""
        reason = await self._check_budget_before_step(node)
        if reason:
            self._handle_budget_exceeded(reason)
            raise RuntimeError(f"Execution blocked by budget constraint: {reason}")

    def _check_budget_after_step(self) -> Optional[str]:
        budget = self._get_budget()
        counters = self.state.data.get("budget_counters", {})

        max_tokens = budget.get("max_tokens")
        if isinstance(max_tokens, int) and max_tokens >= 0 and int(counters.get("tokens", 0)) > max_tokens:
            return "budget_max_tokens_exceeded"

        max_cost = budget.get("max_cost_usd")
        if isinstance(max_cost, (int, float)) and max_cost >= 0 and float(counters.get("cost_usd", 0.0)) > float(max_cost):
            return "budget_max_cost_exceeded"

        max_duration = budget.get("max_duration_seconds")
        if isinstance(max_duration, int) and max_duration >= 0 and self._execution_started_at is not None:
            elapsed = time.perf_counter() - self._execution_started_at
            if elapsed > max_duration:
                return "budget_max_duration_exceeded"

        return None

    def _handle_budget_exceeded(self, reason: str) -> None:
        budget = self._get_budget()
        on_exceed = str(budget.get("on_exceed", "pause")).lower().strip()
        if on_exceed == "abort":
            self.state.data["execution_paused"] = False
            self.state.data["aborted_reason"] = reason
            return

        self.state.data["execution_paused"] = True
        self.state.data["pause_reason"] = reason

    def resume_from_checkpoint(self, checkpoint_index: int = -1) -> Optional[str]:
        if not self.state.checkpoints:
            raise ValueError("No checkpoints available to resume from")

        checkpoint = self.state.checkpoints[checkpoint_index]
        self.state.data = dict(checkpoint.state)
        self.state.data["resumed_from_checkpoint"] = {
            "node_id": checkpoint.node_id,
            "checkpoint_index": checkpoint_index,
        }
        self.state.data["execution_paused"] = False

        next_node = self._get_next_node(checkpoint.node_id, checkpoint.output)
        self._resume_from_node_id = next_node
        return next_node

    def _serialize_graph(self) -> Dict[str, Any]:
        return {
            "id": self.graph.id,
            "nodes": [
                {
                    "id": node.id,
                    "type": node.type,
                    "config": node.config,
                    "agent": node.agent,
                    "timeout": node.timeout,
                    "retries": node.retries,
                }
                for node in self.graph.nodes
            ],
            "edges": [
                {
                    "from": edge.from_node,
                    "to": edge.to_node,
                    "condition": edge.condition,
                }
                for edge in self.graph.edges
            ],
            "state_schema": self.graph.state_schema,
        }

    def _persist_checkpoint(self, checkpoint: WorkflowCheckpoint) -> None:
        if not (self.persist_checkpoints and self.storage):
            return

        try:
            self.storage.save_checkpoint(
                workflow_id=self.graph.id,
                node_id=checkpoint.node_id,
                state=checkpoint.state,
                output=checkpoint.output,
                status=checkpoint.status,
            )
        except Exception as exc:
            logger.error("Failed to persist checkpoint for node=%s: %s", checkpoint.node_id, exc)

    async def _execute_node(self, node: WorkflowNode, state: Optional[Dict[str, Any]] = None) -> Any:
        """Execute a single node based on its type."""
        if node.type == "llm_call":
            return await self._execute_llm_call(node)
        
        if node.type == "tool_call":
            return await self._execute_tool_call(node)
            
        if node.type == "transform":
            return self._execute_transform(node)
            
        if node.type == "sub_graph":
            return await self._execute_sub_graph(node)
            
        if node.type == "eval":
            return self._execute_eval(node)

        return {"status": "ok", "msg": "noop"}

    async def _execute_llm_call(self, node: WorkflowNode) -> Dict[str, Any]:
        prompt, context = self._prepare_llm_payload(node)
        
        resp = await self._provider_service.generate(prompt, context)
        
        # Quality Analysis (Phase 5 requirement: ROI needs quality)
        from .quality_service import QualityService
        text_output = str(resp.get("content") or resp.get("result") or "")
        quality = QualityService.analyze_output(
            text_output, 
            task_type=context.get("task_type"), 
            expected_format=context.get("expected_format")
        )
        
        return {
            "role": "assistant",
            "content": resp["content"],
            "provider": resp["provider"],
            "model_used": resp["model"],
            "tokens_used": resp["tokens_used"],
            "cost_usd": resp["cost_usd"],
            "quality_rating": quality.model_dump()
        }

    def _prepare_llm_payload(self, node: WorkflowNode) -> tuple[str, Dict[str, Any]]:
        """Renders prompt and prepares context for LLM call."""
        prompt_template = str(node.config.get("prompt", ""))
        
        try:
            if "{" in prompt_template and "}" in prompt_template:
               prompt = prompt_template.format(**self.state.data)
            else:
               prompt = prompt_template
        except Exception as e:
            logger.warning(f"Prompt formatting failed for node {node.id}: {e}")
            prompt = prompt_template

        context = {
            "system": node.config.get("system_prompt"), # Legacy key
            "system_prompt": node.config.get("system_prompt"), # New key
            "model": node.config.get("selected_model") or node.config.get("model"),
            "temperature": node.config.get("temperature", 0.7),
            "task_type": node.config.get("task_type"),
            "node_id": node.id,
            "expected_format": "json" if node.type == "classification" else None
        }
        return prompt, context

    async def _execute_tool_call(self, node: WorkflowNode) -> Dict[str, Any]:
        tool_name = str(node.config.get("tool_name", "")).strip()
        args = node.config.get("arguments") or {}
        
        if not tool_name:
             raise ValueError(f"Node {node.id} missing tool_name")
             
        # Lookup tool in registry
        tool_entry = ToolRegistryService.get_tool(tool_name)
        if not tool_entry:
            raise ValueError(f"Tool {tool_name} not found in registry")
            
        # Check if MCP tool
        mcp_server = tool_entry.metadata.get("mcp_server")
        if mcp_server:
            ops_config = ProviderService.get_config()
            if not ops_config or mcp_server not in ops_config.mcp_servers:
                raise RuntimeError(f"MCP server {mcp_server} not found or disabled")
                
            server_config = ops_config.mcp_servers[mcp_server]
            # Fallback to full name if 'mcp_tool' metadata is missing
            real_tool_name = tool_entry.metadata.get("mcp_tool", tool_name)
            
            async with McpClient(mcp_server, server_config) as client:
                result = await client.call_tool(real_tool_name, args)
                
            return {
                "tool": tool_name,
                "input": args,
                "output": result,
                "mcp_server": mcp_server
            }
        
        # Local tool execution
        if tool_entry.metadata.get("type") == "native":
            return self._execute_native_tool(tool_name, args)

        raise NotImplementedError(f"Local tool execution for {tool_name} not implemented yet")

    def _execute_native_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        # MVP: Hardcoded native tools for safety until dynamic loading is safe
        if tool_name == "core_write_file":
            path = args.get("path")
            content = args.get("content")
            if path and content:
                try:
                    # Basic sandbox check: allow writing only to specific temp/data dirs or current workspace if safe
                    # For MVP: just write
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_text(content, encoding="utf-8")
                    return {"status": "success", "written": len(content)}
                except Exception as e:
                    return {"status": "error", "error": str(e)}
        
        if tool_name == "core_read_file":
            path = args.get("path")
            if path:
                try:
                    if Path(path).exists():
                        return {"content": Path(path).read_text(encoding="utf-8")}
                    return {"error": "file_not_found"}
                except Exception as e:
                    return {"error": str(e)}
        
        return {"error": f"Native tool {tool_name} not found"}

    def _execute_transform(self, node: WorkflowNode) -> Dict[str, Any]:
        operation = node.config.get("operation")
        if operation == "json_extract":
            import json
            source_key = node.config.get("source_key")
            target_key = node.config.get("target_key")
            if source_key and target_key:
                source_val = self.state.data.get(source_key)
                if isinstance(source_val, str):
                    try:
                        # Attempt to find JSON bloch ```json ... ```
                        if "```json" in source_val:
                            start = source_val.find("```json") + 7
                            end = source_val.find("```", start)
                            if end > start:
                                source_val = source_val[start:end].strip()
                        parsed = json.loads(source_val)
                        return {target_key: parsed}
                    except Exception as e:
                        return {"error": f"json_extract_failed: {e}"}
        
        elif operation == "format_string":
            template = node.config.get("template", "")
            target_key = node.config.get("target_key")
            if template and target_key:
                try:
                    formatted = template.format(**self.state.data)
                    return {target_key: formatted}
                except Exception as e:
                    return {"error": f"format_string_failed: {e}"}

        return {"status": "ok", "msg": "transform_noop"}

    async def _execute_sub_graph(self, node: WorkflowNode) -> Dict[str, Any]:
        sub_graph_def = node.config.get("graph")
        if not sub_graph_def:
            raise ValueError("sub_graph node missing 'graph' definition")
        
        # Instantiate new engine for sub-graph
        if isinstance(sub_graph_def, dict):
            if "id" not in sub_graph_def:
                sub_graph_def["id"] = f"{self.graph.id}_sub_{node.id}"
            sub_graph = WorkflowGraph.model_validate(sub_graph_def)
        else:
            sub_graph = sub_graph_def

        input_mapping = node.config.get("input_mapping")
        initial_state = {}
        if input_mapping:
             for pk, ck in input_mapping.items():
                 if pk in self.state.data:
                     initial_state[ck] = self.state.data[pk]
        else:
            initial_state = self.state.data.copy()
        
        # Remove budget counters to start sub-graph from 0 usage
        initial_state.pop("budget_counters", None)
        initial_state.pop("step_logs", None)
        initial_state.pop("trace_id", None)

        sub_engine = GraphEngine(
            graph=sub_graph,
            max_iterations=self.max_iterations,
            storage=self.storage,
            persist_checkpoints=self.persist_checkpoints
        )
        
        sub_result = await sub_engine.execute(initial_state=initial_state)
        
        output_mapping = node.config.get("output_mapping")
        result_data = {}
        if output_mapping:
            for ck, pk in output_mapping.items():
                if ck in sub_result.data:
                    result_data[pk] = sub_result.data[ck]
        
        # Extract metrics
        sub_counters = sub_result.data.get("budget_counters", {})
        tokens_used = int(sub_counters.get("tokens", 0))
        cost_usd = float(sub_counters.get("cost_usd", 0.0))

        return {
            "sub_graph_id": sub_graph.id,
            "status": "completed",
            "output": result_data,
            "tokens_used": tokens_used,
            "cost_usd": cost_usd
        }

    def _execute_eval(self, node: WorkflowNode) -> Dict[str, Any]:
        from .evals_service import EvalsService
        from ..ops_models import EvalJudgeConfig, EvalGoldenCase

        expected = node.config.get("expected_state")
        case_id = node.config.get("case_id", f"eval_{node.id}")
        
        adhoc_case = EvalGoldenCase(
             case_id=case_id,
             input_state={},
             expected_state=expected or {},
             threshold=node.config.get("threshold", 1.0)
        )
        judge_config = EvalJudgeConfig(enabled=False)
        
        score, reason = EvalsService._score_case(
            expected_state=adhoc_case.expected_state,
            actual_state=self.state.data,
            judge=judge_config
        )
        
        passed = score >= adhoc_case.threshold
        return {
            "eval_passed": passed,
            "score": score,
            "reason": reason
        }

    def _get_next_node(self, node_id: str, output: Any) -> Optional[str]:
        edges = self._edges_from.get(node_id, [])
        if not edges:
            return None
        
        for edge in edges:
            if edge.condition:
                if self._evaluate_condition(edge.condition, output):
                    return edge.to_node
            else:
                return edge.to_node
                
        return None

    def _evaluate_condition(self, condition: str, output: Any) -> bool:
        """Condition evaluator."""
        try:
            # support "key==value", "key!=value", "key" (truthy)
            if not isinstance(output, dict):
                # If output is not dict, maybe condition is checking just boolean truthiness of output?
                # But our nodes usually return dicts.
                return False
                
            if "==" in condition:
                key, val = condition.split("==", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                # primitive type conversion guess
                if val.lower() == "true": val = True
                elif val.lower() == "false": val = False
                
                return str(output.get(key)) == str(val)
                
            if "!=" in condition:
                key, val = condition.split("!=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                return str(output.get(key)) != str(val)

            # Check if key exists and is truthy
            return bool(output.get(condition))
            
        except Exception:
            return False

    @staticmethod
    def _parse_iso_ts(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            txt = str(value)
            if txt.endswith("Z"):
                txt = txt[:-1] + "+00:00"
            return datetime.fromisoformat(txt).astimezone(timezone.utc)
        except Exception:
            return None



