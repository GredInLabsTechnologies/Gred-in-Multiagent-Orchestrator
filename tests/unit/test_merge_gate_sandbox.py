import asyncio
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tools.gimo_server.services.merge_gate_service import MergeGateService


@pytest.mark.asyncio
async def test_pipeline_fails_without_provided_workspace(monkeypatch):
    """
    WP-01/GAP-01: Verifies that _pipeline fails closed if no workspace is provided.
    """
    statuses = []
    
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.update_run_status",
        lambda run_id, status, msg=None: statuses.append(status),
    )

    await MergeGateService._pipeline("run1", repo_id="default", source_ref="src", target_ref="tgt", provided_workspace=None)
    
    assert "WORKER_CRASHED" in statuses
    assert len(statuses) == 1


@pytest.mark.asyncio
async def test_pipeline_uses_provided_workspace(monkeypatch, tmp_path):
    """
    WP-01/GAP-01: Verifies that _pipeline uses the provisioned workspace correctly.
    """
    fake_workspace = tmp_path / "sandbox"
    fake_workspace.mkdir()
    
    calls = {"tests": [], "lint": [], "dry": [], "merge": []}
    statuses = []

    stages = []
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.set_run_stage",
        lambda run_id, stage, msg=None: stages.append(stage),
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
        lambda base_dir, src, tgt: (calls["dry"].append(base_dir) or True, "ok"),
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.GitService.get_head_commit",
        lambda base_dir: "commit_hash",
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.GitService.perform_merge",
        lambda base_dir, src, tgt: (calls["merge"].append(base_dir) or True, "ok"),
    )

    await MergeGateService._pipeline("run2", repo_id="default", source_ref="src", target_ref="tgt", provided_workspace=str(fake_workspace))
    
    assert statuses[-1] == "done"
    assert "gate_sandbox" in stages
    assert calls["tests"][0] == fake_workspace
    assert calls["lint"][0] == fake_workspace
    assert calls["dry"][0] == fake_workspace
    assert calls["merge"][0] == fake_workspace


@pytest.mark.asyncio
async def test_execute_run_fails_if_workspace_missing_for_high_risk(monkeypatch):
    """
    WP-01/GAP-01: Verifies that execute_run rejects high-risk runs without workspace_path.
    """
    run_id = "run3"
    
    # Mock OpsService to return a high-risk run
    class FakeRun:
        approved_id = "app1"
        repo_id = "default"
        risk_score = 10.0
        policy_decision_id = "p1"

    class FakeApproved:
        draft_id = "d1"

    class FakeDraft:
        context = {
            "intent_effective": "CODE_PATCH",
            "workspace_path": None # Missing!
        }

    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.OpsService.get_run", lambda rid: FakeRun())
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.OpsService.get_approved", lambda aid: FakeApproved())
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.OpsService.get_draft", lambda did: FakeDraft())
    
    statuses = []
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.update_run_status",
        lambda rid, status, msg=None: statuses.append(status),
    )
    monkeypatch.setattr(
        "tools.gimo_server.services.merge_gate_service.OpsService.append_log",
        lambda rid, level, msg: None,
    )

    result = await MergeGateService.execute_run(run_id)
    
    assert result is True # Returns True because it handled the run (failed it)
    assert "WORKER_CRASHED" in statuses


@pytest.mark.asyncio
async def test_execute_run_bypasses_for_low_risk(monkeypatch):
    """
    Verifies that low-risk intents still bypass the git pipeline.
    """
    run_id = "run4"
    
    class FakeRun:
        approved_id = "app1"
        repo_id = "default"
        risk_score = 0.0
        policy_decision_id = "p1"

    class FakeApproved:
        draft_id = "d1"

    class FakeDraft:
        context = {
            "intent_effective": "DOC_UPDATE",
            "workspace_path": None
        }

    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.OpsService.get_run", lambda rid: FakeRun())
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.OpsService.get_approved", lambda aid: FakeApproved())
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.OpsService.get_draft", lambda did: FakeDraft())
    monkeypatch.setattr("tools.gimo_server.services.merge_gate_service.OpsService.append_log", lambda rid, level, msg: None)

    result = await MergeGateService.execute_run(run_id)
    
    assert result is False # Bypassed, delegation to RunWorker
