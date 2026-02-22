from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from ..config import OPS_DATA_DIR

logger = logging.getLogger("orchestrator.custom_plans")

PLANS_DIR = OPS_DATA_DIR / "custom_plans"


# ──────────────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────────────


class PlanNodePosition(BaseModel):
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
    nodes: List[PlanNode] = Field(default_factory=list)
    edges: List[PlanEdge] = Field(default_factory=list)
    status: str = "draft"   # draft | approved | running | done | error
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_log: List[Dict[str, Any]] = Field(default_factory=list)


class CreatePlanRequest(BaseModel):
    name: str
    description: str = ""
    nodes: List[PlanNode] = Field(default_factory=list)
    edges: List[PlanEdge] = Field(default_factory=list)


class UpdatePlanRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[List[PlanNode]] = None
    edges: Optional[List[PlanEdge]] = None


# ──────────────────────────────────────────────────────────────────────────────
# Service
# ──────────────────────────────────────────────────────────────────────────────

class CustomPlanService:
    """File-backed service for user-defined execution graphs."""

    @classmethod
    def _ensure_dir(cls) -> None:
        PLANS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _plan_path(cls, plan_id: str) -> Path:
        return PLANS_DIR / f"{plan_id}.json"

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
        plan = CustomPlan(id=plan_id, name=req.name, description=req.description,
                          nodes=req.nodes, edges=req.edges)
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
        cls._save(updated)
        return updated

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
    async def execute_plan(cls, plan_id: str) -> Optional[CustomPlan]:
        """Execute a plan layer by layer, respecting dependencies."""
        from ..services.provider_service import ProviderService
        from ..services.notification_service import NotificationService

        plan = cls.get_plan(plan_id)
        if not plan:
            return None

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

            for node_id in layer:
                await cls._execute_node(plan, node_map, node_id, plan_id)

            cls._save(plan)

        # Final status
        all_done = all(n.status in ("done", "skipped") for n in plan.nodes)
        plan.status = "done" if all_done else "error"
        cls._save(plan)
        await NotificationService.publish("custom_plan_finished", {
            "plan_id": plan_id, 
            "status": plan.status
        })
        return plan
