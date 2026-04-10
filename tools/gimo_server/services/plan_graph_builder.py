import json
import logging
from typing import Any, Dict, List, Tuple

from .ops import OpsService
from .task_descriptor_service import TaskDescriptorService

logger = logging.getLogger("orchestrator.plan_graph_builder")


def _resolve_plan_payload(plan_data: Any) -> tuple[Dict[str, Any], str | None]:
    resolved_draft_id = getattr(plan_data, "id", None)
    payload = plan_data

    if hasattr(plan_data, "approved_id"):
        approved = OpsService.get_approved(plan_data.approved_id)
        if not approved or not approved.content:
            raise ValueError("Run does not reference plan content")
        resolved_draft_id = approved.draft_id
        payload = approved.content
    elif hasattr(plan_data, "content"):
        payload = getattr(plan_data, "content", None)

    if payload is None:
        raise ValueError("Missing plan payload")
    if isinstance(payload, str):
        payload = json.loads(payload)

    return TaskDescriptorService.coerce_plan_data(payload), resolved_draft_id


def build_graph_from_ops_plan(plan_data: Any, draft_id: str = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Converts legacy OpsPlan content or canonical plan content into ReactFlow nodes and edges.
    Injects metadata for the Agent Observatory while preserving read-old/write-new compatibility.
    """
    try:
        plan_payload, resolved_draft_id = _resolve_plan_payload(plan_data)
        resolved_draft_id = draft_id or resolved_draft_id
        normalized_plan = TaskDescriptorService.normalize_plan_data(plan_payload)
        raw_tasks = plan_payload.get("tasks") or []

        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        total = len(normalized_plan["tasks"])

        worker_count = max(total - 1, 1)
        worker_spacing_y = 140
        worker_block_height = (worker_count - 1) * worker_spacing_y
        worker_start_y = -worker_block_height / 2

        for i, task in enumerate(normalized_plan["tasks"]):
            raw_task = raw_tasks[i] if i < len(raw_tasks) and isinstance(raw_tasks[i], dict) else {}
            is_orchestrator = i == 0

            if is_orchestrator:
                x, y = 0, 0
            else:
                x = 450
                y = worker_start_y + (i - 1) * worker_spacing_y

            node_data = {
                "label": task["title"],
                "status": raw_task.get("status") or "pending",
                "task_description": task["description"],
            }

            if raw_task.get("agent_assignee"):
                assignee = raw_task["agent_assignee"]
                node_data.update(
                    {
                        "system_prompt": assignee.get("system_prompt", ""),
                        "agent_config": {
                            "model": assignee.get("model"),
                            "role": assignee.get("role"),
                            "goal": assignee.get("goal"),
                            "backstory": assignee.get("backstory"),
                        },
                        "instructions": assignee.get("instructions", []),
                        "estimated_tokens": len(assignee.get("system_prompt", "")) // 4,
                        "editable": True,
                    }
                )
            else:
                node_data.update(
                    {
                        "system_prompt": task.get("role_definition", ""),
                        "agent_config": {
                            "model": task.get("requested_model"),
                            "role": task.get("requested_role"),
                        },
                        "estimated_tokens": len(task.get("role_definition", "")) // 4,
                        "editable": True,
                    }
                )
                if raw_task.get("task_descriptor") is not None:
                    node_data["task_descriptor"] = raw_task["task_descriptor"]
                if raw_task.get("task_fingerprint") is not None:
                    node_data["task_fingerprint"] = raw_task["task_fingerprint"]

            node_data["plan"] = {
                "id": plan_payload.get("id") or resolved_draft_id or "draft_plan",
                "draft_id": resolved_draft_id,
                "tasks": [
                    {
                        "id": normalized_task["id"],
                        "description": normalized_task["description"],
                        "status": (
                            raw_tasks[idx].get("status", "pending")
                            if idx < len(raw_tasks) and isinstance(raw_tasks[idx], dict)
                            else "pending"
                        ),
                    }
                    for idx, normalized_task in enumerate(normalized_plan["tasks"])
                ],
            }

            nodes.append(
                {
                    "id": task["id"],
                    "type": "orchestrator" if is_orchestrator else "bridge",
                    "data": node_data,
                    "position": {"x": x, "y": y},
                }
            )

            if task["depends_on"]:
                for dep_id in task["depends_on"]:
                    edges.append(
                        {
                            "id": f"e-{dep_id}-{task['id']}",
                            "source": dep_id,
                            "target": task["id"],
                            "animated": True,
                            "style": {"stroke": "#0a84ff", "strokeWidth": 2},
                        }
                    )
            elif not is_orchestrator and total > 1:
                orch_id = normalized_plan["tasks"][0]["id"]
                edges.append(
                    {
                        "id": f"e-{orch_id}-{task['id']}",
                        "source": orch_id,
                        "target": task["id"],
                        "animated": True,
                        "style": {"stroke": "#32d74b", "strokeWidth": 2},
                    }
                )

        return nodes, edges

    except Exception as e:
        logger.error("Error building graph from plan: %s", e)
        return [], []
