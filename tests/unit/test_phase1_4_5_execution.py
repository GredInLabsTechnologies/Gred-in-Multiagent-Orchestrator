import pytest
import asyncio
from typing import Dict, Any
from pathlib import Path
from types import SimpleNamespace

from tools.gimo_server.services.sub_agent_manager import SubAgentManager
from tools.gimo_server.services.merge_gate_service import MergeGateService

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

    # 2. Legacy flow without provisioned workspace (just to verify it still works)
    legacy_request = SimpleNamespace(modelPreference="test_model", constraints={})
    agent_legacy = await SubAgentManager.create_sub_agent("parent_123", legacy_request)
    assert agent_legacy.worktreePath is not None
    assert str(tmp_path) in agent_legacy.worktreePath
    assert len(worktrees_added) == 1, "add_worktree should be called for legacy flow"


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

    assert statuses[-1] == "done"
    assert len(calls["add"]) == 0, "_create_sandbox_worktree should not be called"
    assert len(calls["remove"]) == 0, "_cleanup_sandbox_worktree should not be called"
    
    assert str(calls["tests"][0]) == str(Path(provisioned_workspace)), "Tests should run in provisioned workspace"
    assert str(calls["lint"][0]) == str(Path(provisioned_workspace)), "Lint should run in provisioned workspace"
    assert str(calls["dry"][0][0]) == str(Path(provisioned_workspace)), "Dry run merge should use provisioned workspace"
    assert str(calls["merge"][0][0]) == str(Path(provisioned_workspace)), "Perform merge should use provisioned workspace"
