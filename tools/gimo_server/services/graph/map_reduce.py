"""MapReduceMixin — Fase 3 de GraphEngine v2.

Ejecuta fan-out paralelo vía SendAction con:
- Semaphore para limitar paralelismo
- Budget distribuido por instancia
- Execution proof por cada instancia
- Resultados mergeados via StateManager
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tools.gimo_server.models.workflow import SendAction

logger = logging.getLogger("orchestrator.services.map_reduce")

_DEFAULT_MAX_PARALLEL = 4


class MapReduceMixin:
    """Fan-out paralelo + merge de resultados via StateManager."""

    async def _execute_send_actions(
        self,
        sends: List[SendAction],
        node_id: str = "",
    ) -> None:
        if not sends:
            return

        max_parallel = int(self.state.data.get("send_max_parallel", _DEFAULT_MAX_PARALLEL))
        semaphore = asyncio.Semaphore(max_parallel)

        # Distribuir budget equitativamente entre instancias
        budget_per_send = self._split_budget(len(sends))

        async def run_one(idx: int, send: SendAction) -> Dict[str, Any]:
            async with semaphore:
                target_node = self._nodes_by_id.get(send.node)
                if not target_node:
                    raise ValueError(f"Send target node '{send.node}' not found in graph")

                instance_state = {**self.state.data, **send.state}
                if budget_per_send:
                    instance_state["budget"] = {
                        **instance_state.get("budget", {}),
                        **budget_per_send,
                    }

                result = await self._execute_node(target_node, instance_state)
                return result if isinstance(result, dict) else {}

        tasks = [run_one(i, s) for i, s in enumerate(sends)]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        proofs: List[Dict[str, Any]] = []
        for i, (send, result) in enumerate(zip(sends, raw_results)):
            if isinstance(result, Exception):
                logger.warning("Send instance %d (node=%s) failed: %s", i, send.node, result)
                proofs.append({"index": i, "node": send.node, "ok": False, "error": str(result)})
            else:
                self._state_manager.apply_update(self.state.data, result)
                proofs.append({"index": i, "node": send.node, "ok": True})

        self.state.data.setdefault("send_proofs", []).append(proofs)

        # GICS: registrar stats
        self._record_send_stats(node_id, sends, proofs)

    def _split_budget(self, n: int) -> Dict[str, Any]:
        if n <= 0:
            return {}
        budget = self.state.data.get("budget")
        if not isinstance(budget, dict):
            return {}
        result = {}
        for k, v in budget.items():
            if isinstance(v, (int, float)) and k not in ("on_exceed",):
                result[k] = v / n
        return result

    def _record_send_stats(
        self,
        node_id: str,
        sends: List[SendAction],
        proofs: List[Dict[str, Any]],
    ) -> None:
        gics = getattr(self, "_gics", None)
        if not gics:
            return
        key = f"ops:send_stats:{self.graph.id}:{node_id}"
        ok = sum(1 for p in proofs if p.get("ok"))
        try:
            gics.put(key, {
                "total": len(sends),
                "ok": ok,
                "failed": len(sends) - ok,
                "nodes": [s.node for s in sends],
            })
        except Exception as e:
            logger.debug("GICS send_stats record failed: %s", e)
