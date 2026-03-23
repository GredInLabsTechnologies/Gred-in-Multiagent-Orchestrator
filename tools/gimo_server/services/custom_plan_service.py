from __future__ import annotations

import logging
import os
import time
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from ..config import OPS_DATA_DIR
from ..ops_models import CostEvent

logger = logging.getLogger("orchestrator.custom_plans")

PLANS_DIR = OPS_DATA_DIR / "custom_plans"


# Models
# ──────────────────────────────────────────────────────────────────────────────


class PlanNodePosition(BaseModel):
    """Define las coordenadas de un nodo en el plano 2D visual."""
    x: float = 0
    y: float = 0


class PlanNode(BaseModel):
    """A single node in the execution graph."""
    id: str
    label: str
    prompt: str = ""
    model: str = "auto"                          # "auto", "qwen2.5-coder:32b", "gpt-4o", etc.
    provider: str = "auto"                       # "auto", "ollama", "openai", etc.
    role: str = "worker"                         # "worker", "reviewer", "researcher"
    node_type: str = "worker"                    # orchestrator | worker | reviewer | researcher | tool | human_gate
    role_definition: str = ""
    is_orchestrator: bool = False
    depends_on: List[str] = Field(default_factory=list)  # IDs of upstream nodes
    status: str = "pending"                      # pending | running | done | error | skipped
    output: Optional[str] = None
    error: Optional[str] = None
    position: PlanNodePosition = Field(default_factory=PlanNodePosition)
    config: Dict[str, Any] = Field(default_factory=dict)  # extra config per node


class PlanEdge(BaseModel):
    """Dependency edge between nodes."""
    id: str
    source: str   # node ID
    target: str   # node ID


class CustomPlan(BaseModel):
    """A user-defined execution graph."""
    id: str
    name: str
    description: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)
    nodes: List[PlanNode] = Field(default_factory=list)
    edges: List[PlanEdge] = Field(default_factory=list)
    status: str = "draft"   # draft | approved | running | done | error
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_log: List[Dict[str, Any]] = Field(default_factory=list)


class CreatePlanRequest(BaseModel):
    """Esquema para crear un plan de ejecucion (CustomPlan)."""
    name: str
    description: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)
    nodes: List[PlanNode] = Field(default_factory=list)
    edges: List[PlanEdge] = Field(default_factory=list)


class UpdatePlanRequest(BaseModel):
    """Esquema para actualizar metadatos de un CustomPlan."""
    name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[List[PlanNode]] = None
    edges: Optional[List[PlanEdge]] = None


# Service
# ──────────────────────────────────────────────────────────────────────────────

def llm_response_to_plan_nodes(
    plan_data: Dict[str, Any],
) -> tuple[List[PlanNode], List[PlanEdge]]:
    """Convert LLM-generated JSON plan (tasks[].agent_assignee) to PlanNode[]+PlanEdge[].

    Accepts the standard OpsPlan-shaped dict:
      { "tasks": [ { "id", "title", "description", "depends",
                      "agent_assignee": { "role", "model", "system_prompt", ... } } ] }

    Returns (nodes, edges) ready for CustomPlan creation.
    """
    tasks = plan_data.get("tasks", [])
    if not tasks:
        raise ValueError("Plan data contains no tasks")

    nodes: List[PlanNode] = []
    edges: List[PlanEdge] = []
    task_ids = {t.get("id", f"t_{i}") for i, t in enumerate(tasks)}

    depth_map, layer_index = _calculate_layout(tasks, task_ids)

    for i, task in enumerate(tasks):
        tid = task.get("id", f"t_{i}")
        title = task.get("title", f"Task {i}")
        desc = task.get("description", "")
        agent = task.get("agent_assignee") or {}
        depends = [d for d in (task.get("depends") or []) if d in task_ids]
        scope = task.get("scope", "")

        role_raw = (agent.get("role") or "worker").lower()
        role_map = {
            "lead orchestrator": "orchestrator",
            "orchestrator": "orchestrator",
            "reviewer": "reviewer",
            "researcher": "researcher",
            "tool": "tool",
            "human_gate": "human_gate",
        }
        node_type = role_map.get(role_raw, "worker")
        is_orch = node_type == "orchestrator" or scope == "bridge"
        if is_orch:
            node_type = "orchestrator"

        prompt_parts = []
        if desc:
            prompt_parts.append(desc)
        if agent.get("system_prompt"):
            prompt_parts.append(agent["system_prompt"])

        depth = depth_map.get(tid, 0)
        idx_in_layer = layer_index.get(tid, 0)

        node = PlanNode(
            id=tid,
            label=title,
            prompt="\n\n".join(prompt_parts),
            model=agent.get("model", "auto"),
            provider="auto",
            role=node_type,
            node_type=node_type,
            role_definition=agent.get("system_prompt", ""),
            is_orchestrator=is_orch,
            depends_on=depends,
            status="pending",
            position=PlanNodePosition(x=250 * depth, y=140 * idx_in_layer),
        )
        nodes.append(node)

        for dep_id in depends:
            edges.append(PlanEdge(
                id=f"e-{dep_id}-{tid}",
                source=dep_id,
                target=tid,
            ))

    return nodes, edges


def _calculate_layout(tasks: List[Dict[str, Any]], task_ids: set) -> tuple[Dict[str, int], Dict[str, int]]:
    depth_map: Dict[str, int] = {}

    def _get_depth(tid: str, visited: set) -> int:
        if tid in depth_map:
            return depth_map[tid]
        if tid in visited:
            return 0
        visited.add(tid)
        task = next((t for t in tasks if t.get("id") == tid), None)
        if not task:
            return 0
        deps = [d for d in (task.get("depends") or []) if d in task_ids]
        d = 0 if not deps else max(_get_depth(dep, visited) for dep in deps) + 1
        depth_map[tid] = d
        return d

    for t in tasks:
        _get_depth(t.get("id", ""), set())

    layers: Dict[int, List[str]] = {}
    for tid, d in depth_map.items():
        layers.setdefault(d, []).append(tid)

    layer_index: Dict[str, int] = {}
    for d, tids in layers.items():
        for idx, tid in enumerate(tids):
            layer_index[tid] = idx

    return depth_map, layer_index


class CustomPlanService:
    """File-backed service for user-defined execution graphs."""

    @classmethod
    def _ensure_dir(cls) -> None:
        PLANS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _plan_path(cls, plan_id: str) -> Path:
        return PLANS_DIR / f"{plan_id}.json"

    # ── Factory from LLM response ──

    @classmethod
    def create_plan_from_llm(cls, plan_data: Dict[str, Any], name: str = "", description: str = "") -> CustomPlan:
        """Create a CustomPlan from an LLM-generated JSON plan dict."""
        nodes, edges = llm_response_to_plan_nodes(plan_data)
        plan_name = name or plan_data.get("title", "AI Generated Plan")
        plan_desc = description or plan_data.get("objective", "")
        req = CreatePlanRequest(name=plan_name, description=plan_desc, nodes=nodes, edges=edges)
        return cls.create_plan(req)

    # ── CRUD ──

    @classmethod
    def list_plans(cls) -> List[CustomPlan]:
        cls._ensure_dir()
        plans: List[CustomPlan] = []
        for f in PLANS_DIR.glob("*.json"):
            try:
                plans.append(CustomPlan.model_validate_json(f.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.warning("Failed to parse plan %s: %s", f.name, exc)
        return sorted(plans, key=lambda p: p.created_at, reverse=True)

    @classmethod
    def get_plan(cls, plan_id: str) -> Optional[CustomPlan]:
        cls._ensure_dir()
        p = cls._plan_path(plan_id)
        if not p.exists():
            return None
        return CustomPlan.model_validate_json(p.read_text(encoding="utf-8"))

    @classmethod
    def create_plan(cls, req: CreatePlanRequest) -> CustomPlan:
        cls._ensure_dir()
        plan_id = f"plan_{int(time.time() * 1000)}_{os.urandom(2).hex()}"
        plan = CustomPlan(
            id=plan_id, 
            name=req.name, 
            description=req.description,
            context=req.context,
            nodes=req.nodes, 
            edges=req.edges
        )
        cls._validate_plan(plan)
        cls._save(plan)
        logger.info("Plan created: %s (%s)", plan.name, plan.id)
        return plan

    @classmethod
    def update_plan(cls, plan_id: str, req: UpdatePlanRequest) -> Optional[CustomPlan]:
        plan = cls.get_plan(plan_id)
        if not plan:
            return None
        if plan.status not in ("draft", "error"):
            return None  # can't edit while running

        data = plan.model_dump()
        for field, val in req.model_dump(exclude_none=True).items():
            data[field] = val
        data["updated_at"] = datetime.now(timezone.utc)
        updated = CustomPlan.model_validate(data)
        cls._validate_plan(updated)
        cls._save(updated)
        return updated

    @classmethod
    def _validate_plan(cls, plan: CustomPlan) -> None:
        node_ids = {n.id for n in plan.nodes}
        if len(node_ids) != len(plan.nodes):
            raise ValueError("Duplicate node IDs are not allowed")

        for edge in plan.edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                raise ValueError(f"Edge '{edge.id}' references unknown nodes")

        for node in plan.nodes:
            missing = [dep for dep in node.depends_on if dep not in node_ids]
            if missing:
                raise ValueError(f"Node '{node.id}' depends on missing nodes: {missing}")

        orchestrators = [
            n for n in plan.nodes
            if n.is_orchestrator or n.node_type == "orchestrator" or n.role == "orchestrator"
        ]
        if len(orchestrators) != 1:
            raise ValueError("Plan must have exactly one orchestrator node")

        cls._assert_no_cycles(plan.nodes)

    @classmethod
    def _assert_no_cycles(cls, nodes: List[PlanNode]) -> None:
        graph: Dict[str, List[str]] = {n.id: [] for n in nodes}
        for node in nodes:
            for dep in node.depends_on:
                graph.setdefault(dep, []).append(node.id)

        visited: set[str] = set()
        for nid in graph:
            if nid not in visited:
                if cls._has_cycle_dfs(nid, graph, visited, set()):
                    raise ValueError("Plan contains dependency cycles")

    @classmethod
    def _has_cycle_dfs(cls, nid: str, graph: Dict[str, List[str]], visited: set[str], in_stack: set[str]) -> bool:
        visited.add(nid)
        in_stack.add(nid)
        for nxt in graph.get(nid, []):
            if nxt not in visited:
                if cls._has_cycle_dfs(nxt, graph, visited, in_stack):
                    return True
            elif nxt in in_stack:
                return True
        in_stack.remove(nid)
        return False

    @classmethod
    def validate_plan(cls, plan: CustomPlan) -> None:
        cls._validate_plan(plan)

    @classmethod
    def delete_plan(cls, plan_id: str) -> bool:
        p = cls._plan_path(plan_id)
        if p.exists():
            p.unlink()
            return True
        return False

    @classmethod
    def _save(cls, plan: CustomPlan) -> None:
        cls._plan_path(plan.id).write_text(
            plan.model_dump_json(indent=2), encoding="utf-8"
        )

    # ── Execution ──

    @classmethod
    def get_execution_order(cls, plan: CustomPlan) -> List[List[str]]:
        """Compute topological layers for parallel execution."""
        dep_map: Dict[str, set] = {n.id: set(n.depends_on) for n in plan.nodes}
        done: set = set()
        layers: List[List[str]] = []

        while len(done) < len(dep_map):
            layer = [nid for nid, deps in dep_map.items()
                     if nid not in done and deps.issubset(done)]
            if not layer:
                # Cycle detected — break with remaining nodes
                layer = [nid for nid in dep_map if nid not in done]
                layers.append(layer)
                break
            layers.append(layer)
            done.update(layer)
        return layers

    @classmethod
    async def execute_plan(
        cls,
        plan_id: str,
        skill_id: Optional[str] = None,
        skill_run_id: Optional[str] = None,
        skill_command: Optional[str] = None,
    ) -> Optional[CustomPlan]:
        """Execute a plan layer by layer, respecting dependencies."""
        from ..services.notification_service import NotificationService

        plan = cls.get_plan(plan_id)
        if not plan:
            return None

        cls._validate_plan(plan)

        plan.status = "running"
        plan.run_log = []
        cls._save(plan)
        await NotificationService.publish("custom_plan_started", {"plan_id": plan_id, "name": plan.name})

        node_map = {n.id: n for n in plan.nodes}
        layers = cls.get_execution_order(plan)

        for layer_idx, layer in enumerate(layers):
            plan.run_log.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": "info",
                "msg": f"Starting layer {layer_idx}: {layer}",
            })

            total_nodes = max(len(plan.nodes), 1)
            for node_idx, node_id in enumerate(layer):
                await cls._execute_node(
                    plan,
                    node_map,
                    node_id,
                    plan_id,
                    skill_id,
                    skill_run_id,
                    skill_command,
                    node_idx=node_idx,
                    layer_size=len(layer),
                    total_nodes=total_nodes,
                )

            cls._save(plan)

        # Final status
        all_done = all(n.status in ("done", "skipped") for n in plan.nodes)
        plan.status = "done" if all_done else "error"
        cls._save(plan)

        # Notify via custom plan events
        await NotificationService.publish("custom_plan_finished", {
            "plan_id": plan_id, 
            "status": plan.status
        })

        return plan

    @classmethod
    async def _execute_node(
        cls,
        plan: CustomPlan,
        node_map: Dict[str, PlanNode],
        node_id: str,
        plan_id: str,
        skill_id: Optional[str] = None,
        skill_run_id: Optional[str] = None,
        skill_command: Optional[str] = None,
        node_idx: int = 0,
        layer_size: int = 1,
        total_nodes: int = 1,
    ) -> None:
        from ..services.notification_service import NotificationService

        node = node_map[node_id]
        if node.status in ("done", "skipped"):
            return

        completed_before = sum(1 for n in plan.nodes if n.status in ("done", "error", "skipped"))
        start_progress = min(max(completed_before / max(total_nodes, 1), 0.0), 1.0)

        await cls._update_node_status(
            plan_id,
            node,
            "running",
            skill_id,
            skill_run_id,
            skill_command,
            progress=start_progress,
        )

        dep_outputs = [f"[{node_map[d].label}]\n{node_map[d].output}" for d in node.depends_on if node_map.get(d) and node_map[d].output]

        # Short-circuit for orchestrator with no prompt
        if node.node_type == "orchestrator" and not node.prompt.strip():
            await cls._handle_empty_orchestrator(
                plan,
                plan_id,
                node,
                skill_id,
                skill_run_id,
                skill_command,
                total_nodes=total_nodes,
            )
            return

        final_prompt = cls._build_node_prompt(node, dep_outputs)

        # P2: Use AgenticLoopService.run_node() for tool-enabled execution
        try:
            from ..services.agentic_loop_service import AgenticLoopService
            from ..services.storage_service import StorageService
            from ..services.ops_service import OpsService

            # Determine mood from node config or role
            node_mood = node.config.get("mood", "executor")  # Default to executor for plan nodes
            workspace = plan.context.get("workspace_root", ".")

            logger.info(f"[plan-node] Executing {node.id} with mood={node_mood}")

            # Execute node with agentic loop
            result = await asyncio.wait_for(
                AgenticLoopService.run_node(
                    workspace_root=workspace,
                    node_prompt=final_prompt,
                    mood=node_mood,
                    max_turns=10,  # Shorter than main loop
                    temperature=None,  # Use mood default
                    tools=None,  # Use all tools
                    token="plan_executor",
                ),
                timeout=300
            )

            node.output = result.response.strip()
            node.status = "done"
            node.error = None

            # Extract usage from agentic result
            usage = result.usage
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)
            cost_usd = usage.get("cost_usd", 0.0)
            quality_score = 85.0 if node.status == "done" else 40.0
            cascade_level = 0  # No cascade in node execution (simplified)

            try:
                storage = StorageService(OpsService._gics)
                storage.cost.save_cost_event(CostEvent(
                    id=f"ce_{uuid.uuid4().hex[:12]}",
                    workflow_id=plan_id,
                    node_id=node.id,
                    model=str(node.model or "auto"),
                    provider=str(node.provider or "auto"),
                    task_type=str(node.node_type or node.role or "worker"),
                    input_tokens=prompt_tokens,
                    output_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost_usd,
                    quality_score=quality_score,
                    cascade_level=cascade_level,
                    cache_hit=False,
                ))
                cfg = OpsService.get_config()
                snap = storage.cost.get_plan_snapshot(
                    plan_id=plan_id,
                    status=plan.status,
                    autonomy_level=cfg.economy.autonomy_level,
                    days=30,
                )
                await NotificationService.publish("custom_node_economy", {
                    "plan_id": plan_id,
                    "node_id": node.id,
                    "cost_usd": cost_usd,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "roi_score": next((n.roi_score for n in snap.nodes if n.node_id == node.id), 0.0),
                    "roi_band": next((n.roi_band for n in snap.nodes if n.node_id == node.id), 1),
                    "yield_optimized": bool(cascade_level > 0),
                })
                await NotificationService.publish("custom_session_economy", {
                    "plan_id": plan_id,
                    "spend_usd": snap.total_cost_usd,
                    "savings_usd": snap.estimated_savings_usd,
                    "nodes_optimized": snap.nodes_optimized,
                })
            except Exception:
                pass
        except Exception as exc:
            node.status = "error"
            node.error = str(exc)[:500]

        completed_after = sum(1 for n in plan.nodes if n.status in ("done", "error", "skipped"))
        finish_progress = min(max(completed_after / max(total_nodes, 1), 0.0), 1.0)
        await cls._finalize_node_execution(
            plan_id,
            node,
            skill_id,
            skill_run_id,
            skill_command,
            progress=finish_progress,
        )

    @classmethod
    async def _update_node_status(
        cls,
        plan_id: str,
        node: PlanNode,
        status: str,
        skill_id: str = None,
        skill_run_id: str = None,
        skill_command: str = None,
        progress: float = 0.0,
    ) -> None:
        from ..services.notification_service import NotificationService
        node.status = status
        if status == "running":
            node.error = None
        
        await NotificationService.publish("custom_node_status", {"plan_id": plan_id, "node_id": node.id, "status": node.status})
        if skill_run_id and skill_id and status == "running":
            await NotificationService.publish("skill_execution_progress", {
                "skill_run_id": skill_run_id,
                "skill_id": skill_id,
                "command": skill_command,
                "status": "running",
                "progress": progress,
                "message": f"Starting node {node.label}",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
            })

    @classmethod
    async def _handle_empty_orchestrator(
        cls,
        plan: CustomPlan,
        plan_id: str,
        node: PlanNode,
        skill_id: str = None,
        skill_run_id: str = None,
        skill_command: str = None,
        total_nodes: int = 1,
    ) -> None:
        from ..services.notification_service import NotificationService
        node.output = "Orchestrator ready. Delegation graph validated."
        node.status = "done"
        await NotificationService.publish("custom_node_status", {"plan_id": plan_id, "node_id": node.id, "status": node.status, "output": node.output})
        if skill_run_id and skill_id:
            completed_after = sum(1 for n in plan.nodes if n.status in ("done", "error", "skipped"))
            progress = min(max(completed_after / max(total_nodes, 1), 0.0), 1.0)
            await NotificationService.publish("skill_execution_progress", {
                "skill_run_id": skill_run_id,
                "skill_id": skill_id,
                "command": skill_command,
                "status": "running",
                "progress": progress,
                "message": f"Finished node {node.label}",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
            })

    @classmethod
    def _build_node_prompt(cls, node: PlanNode, dep_outputs: List[str]) -> str:
        parts = []
        if node.role_definition.strip():
            parts.append(f"Role definition:\n{node.role_definition.strip()}")
        if dep_outputs:
            parts.append("Context from dependencies:\n" + "\n\n".join(dep_outputs))
        parts.append(node.prompt or f"Execute task for node {node.label}")
        return "\n\n".join(parts)

    @classmethod
    async def _finalize_node_execution(
        cls,
        plan_id: str,
        node: PlanNode,
        skill_id: str = None,
        skill_run_id: str = None,
        skill_command: str = None,
        progress: float = 0.0,
    ) -> None:
        from ..services.notification_service import NotificationService
        await NotificationService.publish("custom_node_status", {
            "plan_id": plan_id, "node_id": node.id, "status": node.status, "output": node.output, "error": node.error
        })
        if skill_run_id and skill_id:
            msg = f"Error in node {node.label}: {node.error}" if node.error else f"Finished node {node.label}"
            await NotificationService.publish("skill_execution_progress", {
                "skill_run_id": skill_run_id,
                "skill_id": skill_id,
                "command": skill_command,
                "status": "running",
                "progress": progress,
                "message": msg,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
            })
