from __future__ import annotations

from tools.gimo_server.services.custom_plan_service import (
    CustomPlan,
    CustomPlanService,
    PlanExecutionBusyError,
    PlanNode,
)


def test_execute_plan_route_returns_409_when_plan_is_busy(test_client, valid_token, tmp_path, monkeypatch):
    plan = CustomPlan(
        id="plan_busy",
        name="busy",
        context={"workspace_root": str(tmp_path)},
        nodes=[PlanNode(id="orch", label="Orchestrator", node_type="orchestrator", role="orchestrator", is_orchestrator=True)],
    )

    monkeypatch.setattr(CustomPlanService, "get_plan", lambda _plan_id: plan)
    monkeypatch.setattr(CustomPlanService, "validate_plan", lambda _plan: None)

    def raise_busy(_plan_id: str) -> None:
        raise PlanExecutionBusyError("Plan is busy")

    monkeypatch.setattr(CustomPlanService, "reserve_plan_execution", raise_busy)

    resp = test_client.post(
        f"/ops/custom-plans/{plan.id}/execute",
        headers={"Authorization": f"Bearer {valid_token}"},
    )

    assert resp.status_code == 409
    assert "busy" in resp.json()["detail"].lower()
