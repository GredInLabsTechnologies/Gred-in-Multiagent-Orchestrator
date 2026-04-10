"""Agent execution patterns for GraphEngine (supervisor_workers, reviewer_loop, handoff)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from tools.gimo_server.services.observability_pkg.observability_service import ObservabilityService

if TYPE_CHECKING:
    from tools.gimo_server.ops_models import WorkflowNode

logger = logging.getLogger("orchestrator.services.graph_engine")


class AgentPatternsMixin:
    """supervisor_workers, reviewer_loop, handoff, and proactive confidence."""

    async def _check_proactive_confidence(self, node) -> Optional[Dict[str, Any]]:
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
                return None

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

    async def _run_agent_task(self, node) -> Dict[str, Any]:
        from tools.gimo_server.ops_models import WorkflowNode

        # 1. Trust Proyectado: EVALUACION PROACTIVA
        doubt_response = await self._check_proactive_confidence(node)
        if doubt_response:
            return doubt_response

        pattern = str(node.config.get("pattern", "single")).strip().lower()

        if pattern == "supervisor_workers":
            return await self._run_supervisor_workers(node)

        if pattern == "reviewer_loop":
            return await self._run_reviewer_loop(node)

        if pattern == "handoff":
            return await self._run_handoff(node)

        # default agent_task behaves as a single executable node
        output = await self._call_execute_node(node)
        if isinstance(output, dict):
            output.setdefault("pattern", "single")
        return output

    async def _run_supervisor_workers(self, node) -> Dict[str, Any]:
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

    async def _run_reviewer_loop(self, node) -> Dict[str, Any]:
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

    async def _run_handoff(self, node) -> Dict[str, Any]:
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

    async def _run_agent_child(self, parent_node, *, child_suffix: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        from tools.gimo_server.ops_models import WorkflowNode
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
