import pytest
import asyncio
from typing import Dict, Any
from pathlib import Path
from types import SimpleNamespace

from tools.gimo_server.services.sub_agent_manager import SubAgentManager
from tools.gimo_server.services.merge_gate_service import MergeGateService
from tools.gimo_server.services.sandbox_service import SandboxService

@pytest.mark.asyncio
async def test_subagent_no_longer_creates_source_worktree(monkeypatch, tmp_path):
    worktrees_added = []
    
    def _add_worktree(repo_root, worktree_path, branch=None):
        worktrees_added.append(worktree_path)

    monkeypatch.setattr("tools.gimo_server.services.sub_agent_manager.GitService.add_worktree", _add_worktree)
    monkeypatch.setattr("tools.gimo_server.services.sub_agent_manager.WORKTREES_DIR", tmp_path / "worktrees")
    monkeypatch.setattr("tools.gimo_server.services.sub_agent_manager.SubAgentManager._persist", lambda: None)
    
    # 1. New flow with provisioned workspace
    provisioned_workspace = "/tmp/ephemeral_workspace_xyz"
    request = SimpleNamespace(workspace_path=provisioned_workspace, modelPreference="test_model", constraints={})
    
    agent = await SubAgentManager.create_sub_agent("parent_123", request)
    assert agent.worktreePath == str(Path(provisioned_workspace))
    assert len(worktrees_added) == 0, "add_worktree should not be called when workspace_path is provided"

    # 2. Missing workspace is rejected instead of falling back to source worktrees
    legacy_request = SimpleNamespace(modelPreference="test_model", constraints={})
    with pytest.raises(ValueError, match="workspace_path is required"):
        await SubAgentManager.create_sub_agent("parent_123", legacy_request)
    assert len(worktrees_added) == 0, "legacy add_worktree fallback must stay disabled"


@pytest.mark.asyncio
async def test_merge_gate_does_not_require_source_worktree(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.get_settings",
        lambda: SimpleNamespace(repo_root_dir=repo_root, ops_data_dir=tmp_path / "ops"),
    )

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

    provisioned_workspace = "/tmp/provided_sandbox"

    await MergeGateService._pipeline(
        "run123", repo_id="default", source_ref="feature/a", target_ref="main", provided_workspace=provisioned_workspace
    )

    assert statuses[-1] == "AWAITING_MERGE"
    assert len(calls["add"]) == 0, "_create_sandbox_worktree should not be called"
    assert len(calls["remove"]) == 0, "_cleanup_sandbox_worktree should not be called"
    
    assert str(calls["tests"][0]) == str(Path(provisioned_workspace)), "Tests should run in provisioned workspace"
    assert str(calls["lint"][0]) == str(Path(provisioned_workspace)), "Lint should run in provisioned workspace"
    assert str(calls["dry"][0][0]) == str(Path(provisioned_workspace)), "Dry run merge should use provisioned workspace"
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

    def _fail_legacy(*_args, **_kwargs):
        raise AssertionError("legacy source-repo worktree APIs should not be used")

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
    monkeypatch.setattr("tools.gimo_server.services.sandbox_service.GitService.create_worktree", _fail_legacy)
    monkeypatch.setattr("tools.gimo_server.services.sandbox_service.GitService.remove_worktree", _fail_legacy)
    monkeypatch.setattr("tools.gimo_server.services.sandbox_service.GitService.delete_branch", _fail_legacy)

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
