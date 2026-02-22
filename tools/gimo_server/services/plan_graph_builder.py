import logging
import json
from typing import Any, Dict, List, Tuple
from ..ops_models import OpsPlan, OpsTask

logger = logging.getLogger("orchestrator.plan_graph_builder")

def build_graph_from_ops_plan(plan_data: Any, draft_id: str = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Converts an OpsPlan (or its dict representation) into ReactFlow nodes and edges.
    Injects high-fidelity metadata for the Agent Observatory.
    """
    try:
        if isinstance(plan_data, str):
            plan_data = json.loads(plan_data)
        
        if isinstance(plan_data, dict):
            plan = OpsPlan.model_validate(plan_data)
        else:
            plan = plan_data

        nodes = []
        edges = []
        total = len(plan.tasks)

        # Layout: first task = Orchestrator (left), rest = Workers (right column)
        worker_count = max(total - 1, 1)
        worker_spacing_y = 140
        worker_block_height = (worker_count - 1) * worker_spacing_y
        worker_start_y = -worker_block_height / 2

        for i, task in enumerate(plan.tasks):
            is_orchestrator = (i == 0)

            if is_orchestrator:
                x, y = 0, 0
            else:
                x = 450
                y = worker_start_y + (i - 1) * worker_spacing_y

            node_data = {
                "label": task.title,
                "status": task.status,
                "task_description": task.description,
            }

            # Inject Disruptive Agent Observatory Metadata
            if task.agent_assignee:
                node_data.update({
                    "system_prompt": task.agent_assignee.system_prompt,
                    "agent_config": {
                        "model": task.agent_assignee.model,
                        "role": task.agent_assignee.role,
                        "goal": task.agent_assignee.goal,
                        "backstory": task.agent_assignee.backstory,
                    },
                    "instructions": task.agent_assignee.instructions,
                    "estimated_tokens": len(task.agent_assignee.system_prompt) // 4,
                    "editable": True
                })
            
            # Map to AgentPlan format for InspectPanel's Plan Tab compatibility
            node_data["plan"] = {
                "id": plan.id,
                "draft_id": draft_id,
                "tasks": [
                    {"id": t.id, "description": t.description, "status": t.status} 
                    for t in plan.tasks
                ]
            }

            nodes.append({
                "id": task.id,
                "type": "bridge" if is_orchestrator else "orchestrator",
                "data": node_data,
                "position": {"x": x, "y": y}
            })

            # Auto-connect workers to orchestrator if no explicit deps
            if task.depends:
                for dep_id in task.depends:
                    edges.append({
                        "id": f"e-{dep_id}-{task.id}",
                        "source": dep_id,
                        "target": task.id,
                        "animated": True,
                        "style": {"stroke": "#0a84ff", "strokeWidth": 2}
                    })
            elif not is_orchestrator and total > 1:
                # Connect worker to orchestrator (first task)
                orch_id = plan.tasks[0].id
                edges.append({
                    "id": f"e-{orch_id}-{task.id}",
                    "source": orch_id,
                    "target": task.id,
                    "animated": True,
                    "style": {"stroke": "#32d74b", "strokeWidth": 2}
                })

        return nodes, edges

    except Exception as e:
        logger.error("Error building graph from plan: %s", e)
        return [], []
