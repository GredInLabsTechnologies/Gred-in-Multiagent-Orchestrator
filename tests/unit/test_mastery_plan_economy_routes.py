from __future__ import annotations

from datetime import datetime, timezone
import asyncio

from tools.gimo_server.ops_models import OpsConfig, PlanEconomySnapshot
from tools.gimo_server.models.economy import UserEconomyConfig
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.custom_plan_service import CustomPlan, PlanEdge, PlanNode
from tools.gimo_server.ops_models import PlanAutonomyUpdateRequest
from tools.gimo_server.routers.ops.mastery_router import (
    get_plan_economy_snapshot,
    update_plan_autonomy,
)


def _override_auth() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


def _build_plan() -> CustomPlan:
    return CustomPlan(
        id="plan_test_1",
        name="Plan test",
        description="",
        nodes=[
            PlanNode(id="n1", label="orchestrator", node_type="orchestrator", role="orchestrator", is_orchestrator=True),
            PlanNode(id="n2", label="worker", node_type="worker", role="worker", depends_on=["n1"]),
        ],
        edges=[PlanEdge(id="e-n1-n2", source="n1", target="n2")],
        status="running",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_get_plan_economy_snapshot_ok(monkeypatch):
    from tools.gimo_server.services.custom_plan_service import CustomPlanService
    from tools.gimo_server.services.ops_service import OpsService
    from tools.gimo_server.services.storage_service import StorageService

    plan = _build_plan()
    cfg = OpsConfig(economy=UserEconomyConfig(autonomy_level="guided"))

    monkeypatch.setattr(CustomPlanService, "get_plan", lambda _pid: plan)
    monkeypatch.setattr(OpsService, "get_config", lambda: cfg)

    class _FakeCost:
        def get_plan_snapshot(self, **kwargs):
            return PlanEconomySnapshot(
                plan_id=kwargs["plan_id"],
                status=kwargs["status"],
                autonomy_level=kwargs["autonomy_level"],
                total_cost_usd=1.23,
                total_tokens=123,
                prompt_tokens=80,
                completion_tokens=43,
                estimated_savings_usd=0.2,
                nodes_optimized=1,
                nodes=[],
            )

    monkeypatch.setattr(StorageService, "__init__", lambda self, *args, **kwargs: setattr(self, "cost", _FakeCost()))

    data = asyncio.run(
        get_plan_economy_snapshot(
            plan_id="plan_test_1",
            auth=_override_auth(),
            days=30,
        )
    )
    assert data.plan_id == "plan_test_1"
    assert data.autonomy_level == "guided"
    assert data.total_cost_usd == 1.23


def test_update_plan_autonomy_updates_selected_nodes(monkeypatch):
    from tools.gimo_server.services.custom_plan_service import CustomPlanService
    from tools.gimo_server.services.ops_service import OpsService
    from tools.gimo_server.services.storage_service import StorageService

    plan = _build_plan()
    cfg = OpsConfig(economy=UserEconomyConfig(autonomy_level="manual"))
    saved = {"called": False}

    monkeypatch.setattr(CustomPlanService, "get_plan", lambda _pid: plan)
    monkeypatch.setattr(CustomPlanService, "_save", lambda _plan: saved.__setitem__("called", True))
    monkeypatch.setattr(OpsService, "get_config", lambda: cfg)
    monkeypatch.setattr(OpsService, "set_config", lambda _cfg: _cfg)

    class _FakeCost:
        def get_plan_snapshot(self, **kwargs):
            return PlanEconomySnapshot(
                plan_id=kwargs["plan_id"],
                status=kwargs["status"],
                autonomy_level=kwargs["autonomy_level"],
                total_cost_usd=0.0,
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                estimated_savings_usd=0.0,
                nodes_optimized=0,
                nodes=[],
            )

    monkeypatch.setattr(StorageService, "__init__", lambda self, *args, **kwargs: setattr(self, "cost", _FakeCost()))

    data = asyncio.run(
        update_plan_autonomy(
            plan_id="plan_test_1",
            body=PlanAutonomyUpdateRequest(level="autonomous", node_ids=["n2"]),
            auth=_override_auth(),
        )
    )
    assert data.autonomy_level == "autonomous"
    assert cfg.economy.autonomy_level == "autonomous"
    assert plan.nodes[1].config.get("autonomy_level") == "autonomous"
    assert saved["called"] is True
