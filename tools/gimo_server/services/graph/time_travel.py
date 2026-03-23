"""TimeTravelMixin — Fase 5 de GraphEngine v2.

Provee:
- replay_from_checkpoint(index) — re-ejecuta desde un checkpoint
- fork_from_checkpoint(index, state_patch) — nueva rama con estado editado
- get_checkpoint_timeline() — lista navegable de checkpoints
"""
from __future__ import annotations

import copy
import logging
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger("orchestrator.services.time_travel")


class TimeTravelMixin:
    """Time-travel: replay y fork desde cualquier checkpoint."""

    # ── Replay ──────────────────────────────────────────────

    def replay_from_checkpoint(self, checkpoint_index: int = -1) -> None:
        """Re-ejecuta el grafo desde el nodo siguiente al checkpoint indicado.

        - Restaura estado del checkpoint (igual que resume_from_checkpoint)
        - Elimina checkpoints posteriores al índice
        - Marca el próximo checkpoint como replayed=True via _replaying flag
        """
        if not self.state.checkpoints:
            raise ValueError("No checkpoints disponibles para replay")

        # Normalizar índice negativo
        idx = checkpoint_index if checkpoint_index >= 0 else len(self.state.checkpoints) + checkpoint_index
        if idx < 0 or idx >= len(self.state.checkpoints):
            raise IndexError(f"checkpoint_index={checkpoint_index} fuera de rango")

        checkpoint = self.state.checkpoints[idx]

        # Restaurar estado del checkpoint (deep copy para aislar de mutaciones futuras)
        self.state.data = copy.deepcopy(checkpoint.state)
        self.state.data["execution_paused"] = False
        self.state.data["replayed_from"] = {
            "node_id": checkpoint.node_id,
            "checkpoint_index": idx,
        }

        # Eliminar checkpoints posteriores a este índice
        self.state.checkpoints = self.state.checkpoints[: idx + 1]

        # Resetear contadores de ciclo acumulados después del checkpoint
        self.state.data.pop("_cycle_counters", None)

        # Determinar nodo siguiente
        next_node = self._get_next_node(checkpoint.node_id, checkpoint.output)
        self._resume_from_node_id = next_node
        self._replaying = True

        self._record_fork_outcome(idx, action="replay")

    # ── Fork ────────────────────────────────────────────────

    def fork_from_checkpoint(
        self,
        checkpoint_index: int = -1,
        state_patch: Optional[Dict[str, Any]] = None,
    ) -> "TimeTravelMixin":
        """Crea un nuevo GraphEngine independiente desde un checkpoint con estado editado.

        El fork hereda todos los checkpoints anteriores con fork_id asignado.
        Retorna el nuevo engine listo para ejecutar.
        """
        if not self.state.checkpoints:
            raise ValueError("No checkpoints disponibles para fork")

        idx = checkpoint_index if checkpoint_index >= 0 else len(self.state.checkpoints) + checkpoint_index
        if idx < 0 or idx >= len(self.state.checkpoints):
            raise IndexError(f"checkpoint_index={checkpoint_index} fuera de rango")

        checkpoint = self.state.checkpoints[idx]
        fork_id = str(uuid.uuid4())

        # Crear nuevo engine del mismo tipo con el mismo grafo
        # Heredar confidence_service y provider_service si están disponibles
        fork_engine = type(self)(
            graph=self.graph,
            max_iterations=self.max_iterations,
            storage=self.storage,
            persist_checkpoints=self.persist_checkpoints,
            workflow_timeout_seconds=self.workflow_timeout_seconds,
            confidence_service=getattr(self, "_confidence_service", None),
            provider_service=getattr(self, "_provider_service", None),
        )

        # Heredar cadena de checkpoints anteriores marcados con fork_id
        inherited = []
        for i, cp in enumerate(self.state.checkpoints[: idx + 1]):
            inherited.append(cp.model_copy(update={"fork_id": fork_id}))
        fork_engine.state.checkpoints = inherited

        # Estado base del checkpoint + patch (deep copy para aislar de mutaciones futuras)
        forked_state = copy.deepcopy(checkpoint.state)
        if state_patch:
            forked_state.update(state_patch)
        forked_state["execution_paused"] = False
        forked_state["fork_id"] = fork_id
        forked_state["forked_from"] = {
            "node_id": checkpoint.node_id,
            "checkpoint_index": idx,
            "parent_workflow_id": self.graph.id,
        }
        fork_engine.state.data = forked_state

        # El fork arranca desde el nodo siguiente al checkpoint
        next_node = self._get_next_node(checkpoint.node_id, checkpoint.output)
        fork_engine._resume_from_node_id = next_node

        self._record_fork_outcome(idx, action="fork", fork_id=fork_id)
        logger.info("Fork creado: fork_id=%s desde checkpoint[%d] node=%s", fork_id, idx, checkpoint.node_id)

        return fork_engine

    # ── Timeline ─────────────────────────────────────────────

    def get_checkpoint_timeline(self) -> List[Dict[str, Any]]:
        """Retorna lista navegable de checkpoints con metadata."""
        timeline = []
        for i, cp in enumerate(self.state.checkpoints):
            timeline.append({
                "index": i,
                "node_id": cp.node_id,
                "status": cp.status,
                "timestamp": cp.timestamp.isoformat(),
                "fork_id": cp.fork_id,
                "replayed": cp.replayed,
                "parent_checkpoint_id": cp.parent_checkpoint_id,
                "has_output": cp.output is not None,
            })
        return timeline

    # ── GICS ─────────────────────────────────────────────────

    def _record_fork_outcome(
        self,
        checkpoint_index: int,
        action: str,
        fork_id: Optional[str] = None,
    ) -> None:
        gics = getattr(self, "_gics", None)
        if not gics:
            return
        key = f"ops:fork_outcomes:{self.graph.id}:{checkpoint_index}"
        payload: Dict[str, Any] = {"action": action, "checkpoint_index": checkpoint_index}
        if fork_id:
            payload["fork_id"] = fork_id
        try:
            gics.put(key, payload)
        except Exception as e:
            logger.debug("GICS fork_outcomes record failed: %s", e)
