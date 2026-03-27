import pytest
import json
from pathlib import Path
from types import SimpleNamespace

from tools.gimo_server.services.sub_agent_manager import SubAgentManager
from tools.gimo_server.services.merge_gate_service import MergeGateService
from tools.gimo_server.services.sandbox_service import SandboxService

@pytest.mark.asyncio
async def test_subagent_no_longer_creates_source_worktree(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.gimo_server.services.sub_agent_manager.SubAgentManager._persist", lambda: None)
    
    # 1. New flow with provisioned workspace
    provisioned_workspace = "/tmp/ephemeral_workspace_xyz"
    request = SimpleNamespace(workspace_path=provisioned_workspace, modelPreference="test_model", constraints={})
    
    agent = await SubAgentManager.create_sub_agent("parent_123", request)
    assert agent.worktreePath == str(Path(provisioned_workspace))

    # 2. Missing workspace is rejected instead of falling back to source worktrees
    legacy_request = SimpleNamespace(modelPreference="test_model", constraints={})
    with pytest.raises(ValueError, match="workspace_path is required"):
        await SubAgentManager.create_sub_agent("parent_123", legacy_request)


@pytest.mark.asyncio
async def test_merge_gate_does_not_require_source_worktree(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    calls = {"add": [], "remove": [], "tests": [], "lint": [], "dry": [], "merge": []}
    statuses = []

    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.OpsService.set_run_stage", lambda *a, **k: None)
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.OpsService.append_log", lambda *a, **k: None)
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.OpsService.update_run_merge_metadata", lambda *a, **k: None)
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.update_run_status",
        lambda run_id, status, msg=None: statuses.append(status),
    )

    def _add(base_dir, worktree_path, branch=None):
        calls["add"].append((base_dir, worktree_path, branch))
        worktree_path.mkdir(parents=True, exist_ok=True)

    def _remove(base_dir, worktree_path):
        calls["remove"].append((base_dir, worktree_path))

    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.add_worktree", _add)
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.remove_worktree", _remove)
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.run_tests", lambda base_dir: (calls["tests"].append(base_dir) or True, "ok"))
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.run_lint_typecheck", lambda base_dir: (calls["lint"].append(base_dir) or True, "ok"))
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.dry_run_merge", lambda *a: (calls["dry"].append(a) or True, "ok"))
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.get_head_commit", lambda base_dir: "c1")
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.perform_merge", lambda *a: (calls["merge"].append(a) or True, "ok"))
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.rollback_to_commit", lambda *a: (True, "ok"))
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.clean_repo_check", lambda *a: True)
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.fetch_local_ref", lambda *a: None)

    provisioned_workspace = "/tmp/provided_sandbox"

    await MergeGateService._pipeline(
        "run123",
        repo_id="default",
        source_ref="feature/a",
        target_ref="main",
        provided_workspace=provisioned_workspace,
        authoritative_repo=str(repo_root),
    )

    assert statuses[-1] == "AWAITING_MERGE"
    assert len(calls["add"]) == 0, "_create_sandbox_worktree should not be called"
    assert len(calls["remove"]) == 0, "_cleanup_sandbox_worktree should not be called"
    
    assert str(calls["tests"][0]) == str(Path(provisioned_workspace).resolve()), "Tests should run in provisioned workspace"
    assert str(calls["lint"][0]) == str(Path(provisioned_workspace).resolve()), "Lint should run in provisioned workspace"
    assert str(calls["dry"][0][0]) == str(repo_root), "Dry run merge should target the authoritative repo"
    assert len(calls["merge"]) == 0, "Real merge must not run before the explicit manual merge step"


def test_sandbox_service_uses_ephemeral_workspace_instead_of_source_worktree(monkeypatch, tmp_path):
    source_repo = tmp_path / "repo"
    source_repo.mkdir()

    settings = SimpleNamespace(
        ephemeral_repos_dir=tmp_path / "ephemeral",
        repo_mirrors_dir=tmp_path / "mirrors",
        purge_quarantine_dir=tmp_path / "quarantine",
    )

    created = []
    destroyed = []

    def _create_workspace(self, source_repo_path, base_commit, branch_name=None, workspace_id=None):
        created.append((Path(source_repo_path), base_commit, branch_name, workspace_id))
        workspace = settings.ephemeral_repos_dir / str(workspace_id)
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def _destroy_workspace(self, workspace_path):
        destroyed.append(Path(workspace_path))

    monkeypatch.setattr("tools.gimo_server.services.sandbox_service.get_settings", lambda: settings)
    monkeypatch.setattr(
        "tools.gimo_server.services.sandbox_service.EphemeralRepoService.create_ephemeral_workspace",
        _create_workspace,
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.sandbox_service.EphemeralRepoService.destroy_workspace",
        _destroy_workspace,
    )

    handle = SandboxService.create_worktree_handle("run123", str(source_repo), base_ref="HEAD")

    assert handle.worktree_path.is_relative_to(settings.ephemeral_repos_dir)
    assert created == [
        (
            source_repo.resolve(),
            "HEAD",
            handle.branch_name,
            SandboxService._workspace_id("run123"),
        )
    ]

    assert SandboxService.cleanup_worktree(handle) is True
    assert destroyed == [handle.worktree_path]


def test_sandbox_service_refuses_legacy_cleanup_path(monkeypatch, tmp_path):
    source_repo = tmp_path / "repo"
    source_repo.mkdir()

    settings = SimpleNamespace(
        ephemeral_repos_dir=tmp_path / "ephemeral",
        repo_mirrors_dir=tmp_path / "mirrors",
        purge_quarantine_dir=tmp_path / "quarantine",
    )

    destroyed = []

    def _destroy_workspace(self, workspace_path):
        destroyed.append(Path(workspace_path))

    monkeypatch.setattr("tools.gimo_server.services.sandbox_service.get_settings", lambda: settings)
    monkeypatch.setattr(
        "tools.gimo_server.services.sandbox_service.EphemeralRepoService.destroy_workspace",
        _destroy_workspace,
    )

    legacy_path = tmp_path / "legacy_worktrees" / "run123"
    legacy_path.mkdir(parents=True)
    handle = SimpleNamespace(
        run_id="run123",
        repo_path=str(source_repo),
        worktree_path=legacy_path,
        branch_name="gimo_legacy",
        base_ref="HEAD",
    )

    assert SandboxService.cleanup_worktree(handle) is False
    assert destroyed == []


@pytest.mark.asyncio
async def test_subagent_reconcile_uses_workspace_paths_instead_of_worktree_inventory(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    inventory_file = runtime_dir / "sub_agents.json"

    existing_workspace = tmp_path / "ephemeral" / "kept"
    existing_workspace.mkdir(parents=True)
    stray_legacy_dir = tmp_path / "worktrees" / "orphan_legacy"
    stray_legacy_dir.mkdir(parents=True)

    inventory_file.write_text(
        json.dumps(
            {
                "kept": {
                    "id": "kept",
                    "parentId": "system",
                    "name": "Kept",
                    "model": "test",
                    "status": "idle",
                    "worktreePath": str(existing_workspace),
                    "config": {"model": "test", "temperature": 0.7, "max_tokens": 2048},
                },
                "ghost": {
                    "id": "ghost",
                    "parentId": "system",
                    "name": "Ghost",
                    "model": "test",
                    "status": "idle",
                    "worktreePath": str(tmp_path / "ephemeral" / "missing"),
                    "config": {"model": "test", "temperature": 0.7, "max_tokens": 2048},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    async def _noop_sync():
        return None

    monkeypatch.setattr("tools.gimo_server.services.sub_agent_manager.INVENTORY_FILE", inventory_file)
    monkeypatch.setattr(SubAgentManager, "sync_with_ollama", classmethod(lambda cls: _noop_sync()))
    SubAgentManager._sub_agents = {}

    await SubAgentManager.startup_reconcile()

    assert "kept" in SubAgentManager._sub_agents
    assert "ghost" not in SubAgentManager._sub_agents
    assert stray_legacy_dir.exists(), "startup reconcile must not treat worktree directories as canonical inventory"


@pytest.mark.asyncio
async def test_subagent_termination_does_not_remove_workspace(monkeypatch, tmp_path):
    workspace = tmp_path / "ephemeral" / "subagent"
    workspace.mkdir(parents=True)

    persisted = []

    monkeypatch.setattr("tools.gimo_server.services.sub_agent_manager.SubAgentManager._persist", lambda: persisted.append(True))
    SubAgentManager._sub_agents = {}

    agent = await SubAgentManager.create_sub_agent(
        "parent_123",
        SimpleNamespace(workspace_path=str(workspace), modelPreference="test_model", constraints={}),
    )

    await SubAgentManager.terminate_sub_agent(agent.id)

    assert workspace.exists()
    assert SubAgentManager._sub_agents[agent.id].status == "terminated"
    assert persisted, "termination should still persist inventory changes"


def test_create_run_provisions_workspace_and_copies_validated_task_spec(monkeypatch, tmp_path):
    from tools.gimo_server.models.core import OpsApproved, OpsDraft
    from tools.gimo_server.services.ops_service import OpsService

    OpsService.OPS_DIR = tmp_path
    OpsService.DRAFTS_DIR = tmp_path / "drafts"
    OpsService.APPROVED_DIR = tmp_path / "approved"
    OpsService.RUNS_DIR = tmp_path / "runs"
    OpsService.RUN_EVENTS_DIR = tmp_path / "run_events"
    OpsService.RUN_LOGS_DIR = tmp_path / "run_logs"
    OpsService.LOCKS_DIR = tmp_path / "locks"
    OpsService.LOCK_FILE = tmp_path / ".ops.lock"
    OpsService.ensure_dirs()

    draft = OpsDraft(
        id="d_1",
        prompt="validated prompt",
        context={
            "validated_task_spec": {
                "base_commit": "abc123",
                "repo_handle": "repo_h",
                "allowed_paths": ["app.py"],
                "acceptance_criteria": "ok",
                "evidence_hash": "hash1",
                "context_pack_id": "ctx1",
                "worker_model": "gpt-4o",
                "requires_manual_merge": True,
            }
        },
    )
    approved = OpsApproved(id="a_1", draft_id="d_1", prompt="validated prompt", content="validated prompt")
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    OpsService._approved_path(approved.id).write_text(approved.model_dump_json(indent=2), encoding="utf-8")

    workspace = tmp_path / "ephemeral" / "run_workspace"
    workspace.mkdir(parents=True)
    monkeypatch.setattr(
        "tools.gimo_server.services.app_session_service.AppSessionService.get_path_from_handle",
        lambda handle: str(tmp_path / "repo"),
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.sandbox_service.SandboxService.create_worktree_handle",
        lambda run_id, repo_path, base_ref="main": SimpleNamespace(worktree_path=workspace),
    )

    run = OpsService.create_run("a_1")

    assert run.validated_task_spec is not None
    assert run.validated_task_spec["workspace_path"] == str(workspace)
    assert run.validated_task_spec["repo_handle"] == "repo_h"


def test_create_run_can_target_source_repo_for_sovereign_surface(monkeypatch, tmp_path):
    from tools.gimo_server.models.core import OpsApproved, OpsDraft
    from tools.gimo_server.services.ops_service import OpsService

    OpsService.OPS_DIR = tmp_path
    OpsService.DRAFTS_DIR = tmp_path / "drafts"
    OpsService.APPROVED_DIR = tmp_path / "approved"
    OpsService.RUNS_DIR = tmp_path / "runs"
    OpsService.RUN_EVENTS_DIR = tmp_path / "run_events"
    OpsService.RUN_LOGS_DIR = tmp_path / "run_logs"
    OpsService.LOCKS_DIR = tmp_path / "locks"
    OpsService.LOCK_FILE = tmp_path / ".ops.lock"
    OpsService.ensure_dirs()

    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    draft = OpsDraft(
        id="d_2",
        prompt="validated prompt",
        context={
            "surface": "operator",
            "workspace_mode": "source_repo",
            "validated_task_spec": {
                "base_commit": "abc123",
                "repo_handle": "repo_h",
                "allowed_paths": ["app.py"],
                "acceptance_criteria": "ok",
                "evidence_hash": "hash1",
                "context_pack_id": "ctx1",
                "worker_model": "gpt-4o",
                "requires_manual_merge": True,
            },
        },
    )
    approved = OpsApproved(id="a_2", draft_id="d_2", prompt="validated prompt", content="validated prompt")
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    OpsService._approved_path(approved.id).write_text(approved.model_dump_json(indent=2), encoding="utf-8")

    monkeypatch.setattr(
        "tools.gimo_server.services.app_session_service.AppSessionService.get_path_from_handle",
        lambda handle: str(repo_root),
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.sandbox_service.SandboxService.create_worktree_handle",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sandbox must not be created")),
    )

    run = OpsService.create_run("a_2")

    assert run.validated_task_spec is not None
    assert run.validated_task_spec["workspace_mode"] == "source_repo"
    assert run.validated_task_spec["workspace_path"] == str(repo_root)


def test_create_run_uses_app_bound_snapshot_for_chatgpt_surface(monkeypatch, tmp_path):
    from tools.gimo_server.models.core import OpsApproved, OpsDraft
    from tools.gimo_server.services.ops_service import OpsService

    OpsService.OPS_DIR = tmp_path
    OpsService.DRAFTS_DIR = tmp_path / "drafts"
    OpsService.APPROVED_DIR = tmp_path / "approved"
    OpsService.RUNS_DIR = tmp_path / "runs"
    OpsService.RUN_EVENTS_DIR = tmp_path / "run_events"
    OpsService.RUN_LOGS_DIR = tmp_path / "run_logs"
    OpsService.LOCKS_DIR = tmp_path / "locks"
    OpsService.LOCK_FILE = tmp_path / ".ops.lock"
    OpsService.ensure_dirs()

    app_snapshot = tmp_path / "app_snapshot"
    app_snapshot.mkdir()

    draft = OpsDraft(
        id="d_app",
        prompt="validated prompt",
        context={
            "surface": "chatgpt_app",
            "workspace_mode": "ephemeral",
            "repo_context_pack": {"session_id": "s_app"},
            "validated_task_spec": {
                "base_commit": "abc123",
                "repo_handle": "repo_h",
                "allowed_paths": ["app.py"],
                "acceptance_criteria": "ok",
                "evidence_hash": "hash1",
                "context_pack_id": "ctx1",
                "worker_model": "gpt-4o",
                "requires_manual_merge": True,
            },
        },
    )
    approved = OpsApproved(id="a_app", draft_id="d_app", prompt="validated prompt", content="validated prompt")
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    OpsService._approved_path(approved.id).write_text(approved.model_dump_json(indent=2), encoding="utf-8")

    observed_repo_paths = []
    workspace = tmp_path / "ephemeral" / "run_workspace"
    workspace.mkdir(parents=True)

    monkeypatch.setattr(
        "tools.gimo_server.services.app_session_service.AppSessionService.get_bound_repo_path",
        lambda session_id: str(app_snapshot) if session_id == "s_app" else None,
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.app_session_service.AppSessionService.get_path_from_handle",
        lambda handle: (_ for _ in ()).throw(AssertionError("chatgpt_app runs must not resolve source repo paths")),
    )

    def _create_handle(run_id, repo_path, base_ref="main"):
        observed_repo_paths.append(repo_path)
        return SimpleNamespace(worktree_path=workspace)

    monkeypatch.setattr(
        "tools.gimo_server.services.sandbox_service.SandboxService.create_worktree_handle",
        _create_handle,
    )

    run = OpsService.create_run("a_app")

    assert observed_repo_paths == [str(app_snapshot)]
    assert run.validated_task_spec is not None
    assert run.validated_task_spec["workspace_path"] == str(workspace)


def test_create_run_for_chatgpt_surface_fails_closed_without_bound_snapshot(monkeypatch, tmp_path):
    from tools.gimo_server.models.core import OpsApproved, OpsDraft
    from tools.gimo_server.services.ops_service import OpsService

    OpsService.OPS_DIR = tmp_path
    OpsService.DRAFTS_DIR = tmp_path / "drafts"
    OpsService.APPROVED_DIR = tmp_path / "approved"
    OpsService.RUNS_DIR = tmp_path / "runs"
    OpsService.RUN_EVENTS_DIR = tmp_path / "run_events"
    OpsService.RUN_LOGS_DIR = tmp_path / "run_logs"
    OpsService.LOCKS_DIR = tmp_path / "locks"
    OpsService.LOCK_FILE = tmp_path / ".ops.lock"
    OpsService.ensure_dirs()

    draft = OpsDraft(
        id="d_app_missing",
        prompt="validated prompt",
        context={
            "surface": "chatgpt_app",
            "workspace_mode": "ephemeral",
            "repo_context_pack": {"session_id": "s_missing"},
            "validated_task_spec": {
                "base_commit": "abc123",
                "repo_handle": "repo_h",
                "allowed_paths": ["app.py"],
                "acceptance_criteria": "ok",
                "evidence_hash": "hash1",
                "context_pack_id": "ctx1",
                "worker_model": "gpt-4o",
                "requires_manual_merge": True,
            },
        },
    )
    approved = OpsApproved(
        id="a_app_missing",
        draft_id="d_app_missing",
        prompt="validated prompt",
        content="validated prompt",
    )
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    OpsService._approved_path(approved.id).write_text(approved.model_dump_json(indent=2), encoding="utf-8")

    monkeypatch.setattr(
        "tools.gimo_server.services.app_session_service.AppSessionService.get_bound_repo_path",
        lambda session_id: None,
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.app_session_service.AppSessionService.get_path_from_handle",
        lambda handle: (_ for _ in ()).throw(AssertionError("chatgpt_app must not fall back to source repos")),
    )

    with pytest.raises(RuntimeError, match="CHATGPT_APP_REPO_SNAPSHOT_UNAVAILABLE"):
        OpsService.create_run("a_app_missing")
