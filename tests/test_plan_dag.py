from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.gimo_server.services.custom_plan_service import CustomPlan, CustomPlanService, PlanNode
from tools.gimo_server.services.sandbox_service import SandboxHandle, SandboxService


@pytest.mark.asyncio
async def test_execute_plan_runs_independent_layer_nodes_in_parallel(monkeypatch, tmp_path: Path):
    plan = CustomPlan(
        id="plan_parallel",
        name="parallel",
        context={"workspace_root": str(tmp_path)},
        nodes=[
            PlanNode(id="orch", label="Orchestrator", node_type="orchestrator", role="orchestrator", is_orchestrator=True),
            PlanNode(id="a", label="A", depends_on=["orch"]),
            PlanNode(id="b", label="B", depends_on=["orch"]),
        ],
    )

    starts: dict[str, float] = {}

    async def fake_publish(*_args, **_kwargs):
        return None

    async def fake_execute_node(
        plan_obj,
        node_map,
        node_id,
        plan_id,
        skill_id=None,
        skill_run_id=None,
        skill_command=None,
        node_idx=0,
        layer_size=1,
        total_nodes=1,
        workspace_override=None,
        repo_root=None,
        base_ref="HEAD",
        execution_id="",
    ):
        starts[node_id] = time.monotonic()
        await asyncio.sleep(0.05)
        node = node_map[node_id]
        node.status = "done"
        node.output = f"done:{node_id}"
        return {
            "node_id": node_id,
            "status": "done",
            "changed_files": [],
            "diff": "",
            "commit_sha": "",
            "branch_name": "",
        }

    monkeypatch.setattr(CustomPlanService, "get_plan", lambda _pid: plan)
    monkeypatch.setattr(CustomPlanService, "_save", lambda _plan: None)
    monkeypatch.setattr(CustomPlanService, "_execute_node", fake_execute_node)
    monkeypatch.setattr("tools.gimo_server.services.notification_service.NotificationService.publish", fake_publish)
    monkeypatch.setattr("tools.gimo_server.services.ops_service.OpsService.get_config", lambda: SimpleNamespace(max_concurrent_runs=4))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_current_branch", lambda _repo: "main")
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.is_worktree_clean", lambda _repo: True)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.create_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.fast_forward_branch", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.delete_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService._run_git", lambda *_args, **_kwargs: (0, "", ""))

    result = await CustomPlanService.execute_plan(plan.id)

    assert result is plan
    assert plan.status == "done"
    assert abs(starts["a"] - starts["b"]) < 0.04


@pytest.mark.asyncio
async def test_execute_plan_persists_running_and_final_node_states(monkeypatch, tmp_path: Path):
    plan = CustomPlan(
        id="plan_persist",
        name="persist",
        context={"workspace_root": str(tmp_path)},
        nodes=[
            PlanNode(id="orch", label="Orchestrator", node_type="orchestrator", role="orchestrator", is_orchestrator=True),
            PlanNode(id="worker", label="Worker", depends_on=["orch"], prompt="do it"),
        ],
    )

    snapshots: list[dict[str, str]] = []
    worktree_path = tmp_path / "wt_worker"
    worktree_path.mkdir()

    async def fake_publish(*_args, **_kwargs):
        return None

    async def fake_run_node(**_kwargs):
        return SimpleNamespace(
            response="done",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost_usd": 0.0},
            finish_reason="stop",
        )

    def record_save(plan_obj):
        snapshots.append({node.id: node.status for node in plan_obj.nodes})

    monkeypatch.setattr(CustomPlanService, "get_plan", lambda _pid: plan)
    monkeypatch.setattr(CustomPlanService, "_save", record_save)
    monkeypatch.setattr("tools.gimo_server.services.notification_service.NotificationService.publish", fake_publish)
    monkeypatch.setattr("tools.gimo_server.services.ops_service.OpsService.get_config", lambda: SimpleNamespace(max_concurrent_runs=2))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.SandboxService.create_worktree_handle", lambda *_args, **_kwargs: SandboxHandle(
        run_id="plan_persist_worker",
        repo_path=str(tmp_path),
        worktree_path=worktree_path,
        branch_name="gimo_branch",
        base_ref="HEAD",
    ))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.SandboxService.cleanup_worktree", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("tools.gimo_server.services.agentic_loop_service.AgenticLoopService.run_node", fake_run_node)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_current_branch", lambda _repo: "main")
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.is_worktree_clean", lambda _repo: True)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.create_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.perform_merge", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.fast_forward_branch", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.delete_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService._run_git", lambda *_args, **_kwargs: (0, "", ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_changed_files", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_diff_text", lambda *_args, **_kwargs: "")
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.commit_all", lambda *_args, **_kwargs: "")

    result = await CustomPlanService.execute_plan(plan.id)

    assert result is plan
    assert any(snapshot.get("worker") == "running" for snapshot in snapshots)
    assert any(snapshot.get("worker") == "done" for snapshot in snapshots)


@pytest.mark.asyncio
async def test_execute_plan_records_successful_nodes_with_high_quality(monkeypatch, tmp_path: Path):
    plan = CustomPlan(
        id="plan_quality",
        name="quality",
        context={"workspace_root": str(tmp_path)},
        nodes=[
            PlanNode(id="orch", label="Orchestrator", node_type="orchestrator", role="orchestrator", is_orchestrator=True),
            PlanNode(id="worker", label="Worker", depends_on=["orch"], prompt="do it"),
        ],
    )

    worktree_path = tmp_path / "wt_quality"
    worktree_path.mkdir()
    saved_events = []

    class _FakeCostStore:
        def save_cost_event(self, event):
            saved_events.append(event)

        def get_plan_snapshot(self, **_kwargs):
            return SimpleNamespace(
                nodes=[SimpleNamespace(node_id="worker", roi_score=0.0, roi_band=1)],
                total_cost_usd=0.0,
                estimated_savings_usd=0.0,
                nodes_optimized=0,
            )

    class _FakeStorageService:
        def __init__(self, _gics):
            self.cost = _FakeCostStore()

    async def fake_publish(*_args, **_kwargs):
        return None

    async def fake_run_node(**_kwargs):
        return SimpleNamespace(
            response="done",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost_usd": 0.0},
            finish_reason="stop",
        )

    monkeypatch.setattr(CustomPlanService, "get_plan", lambda _pid: plan)
    monkeypatch.setattr(CustomPlanService, "_save", lambda _plan: None)
    monkeypatch.setattr("tools.gimo_server.services.notification_service.NotificationService.publish", fake_publish)
    monkeypatch.setattr("tools.gimo_server.services.ops_service.OpsService.get_config", lambda: SimpleNamespace(max_concurrent_runs=2, economy=SimpleNamespace(autonomy_level="balanced")))
    monkeypatch.setattr("tools.gimo_server.services.ops_service.OpsService._gics", object())
    monkeypatch.setattr("tools.gimo_server.services.storage_service.StorageService", _FakeStorageService)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.SandboxService.create_worktree_handle", lambda *_args, **_kwargs: SandboxHandle(
        run_id="plan_quality_worker",
        repo_path=str(tmp_path),
        worktree_path=worktree_path,
        branch_name="gimo_branch",
        base_ref="HEAD",
    ))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.SandboxService.cleanup_worktree", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("tools.gimo_server.services.agentic_loop_service.AgenticLoopService.run_node", fake_run_node)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_current_branch", lambda _repo: "main")
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.is_worktree_clean", lambda _repo: True)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.create_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.perform_merge", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.fast_forward_branch", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.delete_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService._run_git", lambda *_args, **_kwargs: (0, "", ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_changed_files", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_diff_text", lambda *_args, **_kwargs: "")
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.commit_all", lambda *_args, **_kwargs: "")

    result = await CustomPlanService.execute_plan(plan.id)

    assert result is plan
    worker_events = [event for event in saved_events if event.node_id == "worker"]
    assert worker_events
    assert worker_events[-1].quality_score == 85.0


def test_sandbox_service_uses_configured_worktrees_dir():
    from tools.gimo_server.config import WORKTREES_DIR

    assert SandboxService.BASE_WORKTREE_PATH == WORKTREES_DIR


@pytest.mark.asyncio
async def test_execute_plan_uses_unique_worktree_run_ids_per_execution(monkeypatch, tmp_path: Path):
    run_ids: list[str] = []

    def make_plan():
        return CustomPlan(
            id="plan_retryable",
            name="retryable",
            context={"workspace_root": str(tmp_path)},
            nodes=[
                PlanNode(id="orch", label="Orchestrator", node_type="orchestrator", role="orchestrator", is_orchestrator=True),
                PlanNode(id="worker", label="Worker", depends_on=["orch"], prompt="do it"),
            ],
        )

    plans = [make_plan(), make_plan()]

    async def fake_publish(*_args, **_kwargs):
        return None

    async def fake_run_node(**_kwargs):
        return SimpleNamespace(
            response="done",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost_usd": 0.0},
            finish_reason="stop",
        )

    def fake_create_worktree_handle(run_id, repo_path, base_ref="HEAD"):
        run_ids.append(run_id)
        worktree_path = tmp_path / f"wt_{len(run_ids)}"
        worktree_path.mkdir(exist_ok=True)
        return SandboxHandle(
            run_id=run_id,
            repo_path=repo_path,
            worktree_path=worktree_path,
            branch_name=f"branch_{len(run_ids)}",
            base_ref=base_ref,
        )

    monkeypatch.setattr(CustomPlanService, "get_plan", lambda _pid: plans.pop(0))
    monkeypatch.setattr(CustomPlanService, "_save", lambda _plan: None)
    monkeypatch.setattr("tools.gimo_server.services.notification_service.NotificationService.publish", fake_publish)
    monkeypatch.setattr("tools.gimo_server.services.ops_service.OpsService.get_config", lambda: SimpleNamespace(max_concurrent_runs=2))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.SandboxService.create_worktree_handle", fake_create_worktree_handle)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.SandboxService.cleanup_worktree", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("tools.gimo_server.services.agentic_loop_service.AgenticLoopService.run_node", fake_run_node)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_current_branch", lambda _repo: "main")
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.is_worktree_clean", lambda _repo: True)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.create_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.perform_merge", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.fast_forward_branch", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.delete_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService._run_git", lambda *_args, **_kwargs: (0, "", ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_changed_files", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_diff_text", lambda *_args, **_kwargs: "")
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.commit_all", lambda *_args, **_kwargs: "")

    await CustomPlanService.execute_plan("plan_retryable")
    await CustomPlanService.execute_plan("plan_retryable")

    assert len(run_ids) == 2
    assert run_ids[0] != run_ids[1]


@pytest.mark.asyncio
async def test_execute_plan_does_not_persist_done_before_commit(monkeypatch, tmp_path: Path):
    plan = CustomPlan(
        id="plan_commit_failure",
        name="commit failure",
        context={"workspace_root": str(tmp_path)},
        nodes=[
            PlanNode(id="orch", label="Orchestrator", node_type="orchestrator", role="orchestrator", is_orchestrator=True),
            PlanNode(id="worker", label="Worker", depends_on=["orch"], prompt="do it"),
        ],
    )

    snapshots: list[dict[str, str]] = []
    worktree_path = tmp_path / "wt_commit_failure"
    worktree_path.mkdir()

    async def fake_publish(*_args, **_kwargs):
        return None

    async def fake_run_node(**_kwargs):
        return SimpleNamespace(
            response="done",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost_usd": 0.0},
            finish_reason="stop",
        )

    def record_save(plan_obj):
        snapshots.append({node.id: node.status for node in plan_obj.nodes})

    monkeypatch.setattr(CustomPlanService, "get_plan", lambda _pid: plan)
    monkeypatch.setattr(CustomPlanService, "_save", record_save)
    monkeypatch.setattr("tools.gimo_server.services.notification_service.NotificationService.publish", fake_publish)
    monkeypatch.setattr("tools.gimo_server.services.ops_service.OpsService.get_config", lambda: SimpleNamespace(max_concurrent_runs=2))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.SandboxService.create_worktree_handle", lambda *_args, **_kwargs: SandboxHandle(
        run_id="plan_commit_failure_worker",
        repo_path=str(tmp_path),
        worktree_path=worktree_path,
        branch_name="gimo_branch",
        base_ref="HEAD",
    ))
    monkeypatch.setattr("tools.gimo_server.services.agentic_loop_service.AgenticLoopService.run_node", fake_run_node)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_current_branch", lambda _repo: "main")
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.is_worktree_clean", lambda _repo: True)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.create_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.perform_merge", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.fast_forward_branch", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.delete_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService._run_git", lambda *_args, **_kwargs: (0, "", ""))
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_changed_files", lambda *_args, **_kwargs: ["file.py"])
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.get_diff_text", lambda *_args, **_kwargs: "diff")
    monkeypatch.setattr("tools.gimo_server.services.custom_plan_service.GitService.commit_all", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("commit failed")))

    result = await CustomPlanService.execute_plan(plan.id)

    assert result is plan
    assert plan.status == "error"
    assert any(snapshot.get("worker") == "running" for snapshot in snapshots)
    assert any(snapshot.get("worker") == "error" for snapshot in snapshots)
    assert all(snapshot.get("worker") != "done" for snapshot in snapshots)
