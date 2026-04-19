from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("orchestrator.services.storage.workflow")

class WorkflowStorage:
    """Storage logic for workflows and checkpoints.
    Persists entirely via GICS.
    """

    def __init__(self, conn: Optional[Any] = None, gics: Optional[Any] = None):
        self._conn = conn # Kept for backward compatibility
        self.gics = gics

    def ensure_tables(self) -> None:
        """No-op: using GICS."""

    def save_workflow(self, workflow_id: str, data: str) -> None:
        if not self.gics:
            return
            
        if not isinstance(data, str):
            data = json.dumps(data)
            
        try:
            self.gics.put(f"wf:{workflow_id}", {"data": data})
        except Exception as e:
            logger.error("Failed to push workflow %s to GICS: %s", workflow_id, e)

    def save_checkpoint(
        self,
        workflow_id: str,
        node_id: str,
        state: Any,
        output: Optional[Any],
        status: str,
    ) -> None:
        if not self.gics:
            return
            
        state_payload = state if isinstance(state, str) else json.dumps(state)
        output_payload = output if isinstance(output, str) or output is None else json.dumps(output)
        
        try:
            timestamp = int(time.time() * 1000)
            cp_key = f"wf:{workflow_id}:cp:{timestamp}:{node_id}"
            self.gics.put(cp_key, {
                "workflow_id": workflow_id,
                "node_id": node_id,
                "state": state_payload,
                "output": output_payload,
                "status": status,
                "timestamp": timestamp
            })
        except Exception as e:
            logger.error("Failed to push checkpoint for %s to GICS: %s", workflow_id, e)

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        if not self.gics:
            return None
            
        try:
            result = self.gics.get(f"wf:{workflow_id}")
            if result and "fields" in result:
                data = result["fields"].get("data")
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except Exception:
                        pass
                return {
                    "id": workflow_id,
                    "data": data,
                    "created_at": result.get("timestamp"),
                }
        except Exception as e:
            logger.error("Failed to get workflow from GICS: %s", e)
            
        return None

    def list_checkpoints(self, workflow_id: str) -> List[Dict[str, Any]]:
        if not self.gics:
            return []
            
        try:
            prefix = f"wf:{workflow_id}:cp:"
            items = self.gics.scan(prefix=prefix, include_fields=True)
            checkpoints = []
            for item in items:
                fields = item.get("fields", {})
                checkpoints.append({
                    "workflow_id": fields.get("workflow_id"),
                    "node_id": fields.get("node_id"),
                    "state": self._maybe_parse_json(fields.get("state")),
                    "output": self._maybe_parse_json(fields.get("output")),
                    "status": fields.get("status"),
                    "timestamp": fields.get("timestamp"),
                })
            checkpoints.sort(key=lambda x: x.get("timestamp") or 0)
            return checkpoints
        except Exception as e:
            logger.error("Failed to list checkpoints from GICS: %s", e)
            return []

    def _maybe_parse_json(self, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except Exception:
            return value
