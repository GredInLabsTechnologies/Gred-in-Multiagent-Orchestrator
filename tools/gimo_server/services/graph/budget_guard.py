"""Budget enforcement logic for GraphEngine."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tools.gimo_server.ops_models import WorkflowNode

logger = logging.getLogger("orchestrator.services.graph_engine")


class BudgetGuardMixin:
    """Methods related to budget checking and enforcement."""

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
            from tools.gimo_server.services.ops_service import OpsService
            config = OpsService.get_config()
            if config.economy and config.economy.global_budget_usd is not None:
                if self.storage and hasattr(self.storage, "cost"):
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
