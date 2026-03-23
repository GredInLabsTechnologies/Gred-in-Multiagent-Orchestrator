"""Checkpoint persistence and serialization for GraphEngine."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tools.gimo_server.ops_models import WorkflowCheckpoint

logger = logging.getLogger("orchestrator.services.graph_engine")


class CheckpointMixin:
    """Checkpoint management: save, restore, serialize."""

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

    def _persist_checkpoint(self, checkpoint) -> None:
        if not (self.persist_checkpoints and self.storage):
            return

        try:
            self.storage.save_checkpoint(
                workflow_id=self.graph.id,
                node_id=checkpoint.node_id,
                state=checkpoint.state,
                output=checkpoint.output,
                status=checkpoint.status,
                # Fase 5: Time-Travel fields (optional kwargs, backward compat)
                parent_checkpoint_id=getattr(checkpoint, "parent_checkpoint_id", None),
                fork_id=getattr(checkpoint, "fork_id", None),
                replayed=getattr(checkpoint, "replayed", False),
            )
        except TypeError:
            # Storage no acepta los nuevos kwargs — fallback sin ellos
            self.storage.save_checkpoint(
                workflow_id=self.graph.id,
                node_id=checkpoint.node_id,
                state=checkpoint.state,
                output=checkpoint.output,
                status=checkpoint.status,
            )
        except Exception as exc:
            logger.error("Failed to persist checkpoint for node=%s: %s", checkpoint.node_id, exc)

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
            if not isinstance(output, dict):
                return False

            if "==" in condition:
                key, val = condition.split("==", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if val.lower() == "true": val = True
                elif val.lower() == "false": val = False
                return str(output.get(key)) == str(val)

            if "!=" in condition:
                key, val = condition.split("!=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                return str(output.get(key)) != str(val)

            return bool(output.get(condition))

        except Exception:
            return False
