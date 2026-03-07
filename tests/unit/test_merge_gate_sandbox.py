import asyncio
from types import SimpleNamespace

from tools.gimo_server.services.merge_gate_service import MergeGateService


def test_pipeline_uses_sandbox_worktree_and_cleans_up(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.get_settings",
        lambda: SimpleNamespace(repo_root_dir=repo_root, ops_data_dir=tmp_path / "ops"),
    )

    calls = {"add": [], "remove": [], "tests": [], "lint": [], "dry": [], "merge": []}
    statuses = []

    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.set_run_stage",
        lambda run_id, stage, msg=None: None,
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.append_log",
        lambda run_id, level, msg: None,
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.update_run_merge_metadata",
        lambda run_id, **kwargs: None,
    )
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
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.GitService.run_tests",
        lambda base_dir: (calls["tests"].append(base_dir) or True, "ok"),
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.GitService.run_lint_typecheck",
        lambda base_dir: (calls["lint"].append(base_dir) or True, "ok"),
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.GitService.dry_run_merge",
        lambda base_dir, source_ref, target_ref: (calls["dry"].append((base_dir, source_ref, target_ref)) or True, "ok"),
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.GitService.get_head_commit",
        lambda base_dir: "c1",
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.GitService.perform_merge",
        lambda base_dir, source_ref, target_ref: (calls["merge"].append((base_dir, source_ref, target_ref)) or True, "ok"),
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.GitService.rollback_to_commit",
        lambda base_dir, commit_before: (True, "ok"),
    )

    asyncio.run(MergeGateService._pipeline("run123", repo_id="default", source_ref="feature/a", target_ref="main"))

    assert statuses[-1] == "done"
    assert len(calls["add"]) == 1
    sandbox = calls["add"][0][1]
    assert calls["add"][0][0] == repo_root
    assert calls["add"][0][2] == "feature/a"
    assert calls["tests"][0] == sandbox
    assert calls["lint"][0] == sandbox
    assert calls["dry"][0][0] == sandbox
    assert calls["merge"][0][0] == sandbox
    assert calls["remove"][-1] == (repo_root, sandbox)


def test_pipeline_cleans_up_sandbox_when_tests_fail(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.get_settings",
        lambda: SimpleNamespace(repo_root_dir=repo_root, ops_data_dir=tmp_path / "ops"),
    )

    calls = {"remove": []}
    statuses = []

    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.set_run_stage",
        lambda run_id, stage, msg=None: None,
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.append_log",
        lambda run_id, level, msg: None,
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.update_run_merge_metadata",
        lambda run_id, **kwargs: None,
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.update_run_status",
        lambda run_id, status, msg=None: statuses.append(status),
    )

    def _add(base_dir, worktree_path, branch=None):
        worktree_path.mkdir(parents=True, exist_ok=True)

    def _remove(base_dir, worktree_path):
        calls["remove"].append((base_dir, worktree_path))

    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.add_worktree", _add)
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.GitService.remove_worktree", _remove)
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.GitService.run_tests",
        lambda base_dir: (False, "boom"),
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.GitService.run_lint_typecheck",
        lambda base_dir: (True, "ok"),
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.GitService.dry_run_merge",
        lambda base_dir, source_ref, target_ref: (True, "ok"),
    )

    asyncio.run(MergeGateService._pipeline("run124", repo_id="default", source_ref="feature/a", target_ref="main"))

    assert statuses[-1] == "VALIDATION_FAILED_TESTS"
    assert calls["remove"], "sandbox worktree must be removed on failure"
