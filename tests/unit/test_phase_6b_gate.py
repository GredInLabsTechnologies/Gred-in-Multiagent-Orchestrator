import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.gimo_server.models.core import OpsRun
from tools.gimo_server.services.lifecycle_errors import LifecycleProofError, PurgeExecutionError
from tools.gimo_server.services.purge_service import PurgeService


def create_mock_run(run_id: str):
    return OpsRun(
        id=run_id,
        approved_id="a1",
        status="done",
        commit_base="base123",
        commit_after="after456",
        validated_task_spec={},
        model_tier=2,
        risk_score=0.1,
    )


def _settings(repo_root="/repo", worktree_root="/worktrees", ephemeral_root="/ephemeral"):
    return MagicMock(
        repo_root_dir=repo_root,
        worktrees_dir=worktree_root,
        ephemeral_repos_dir=ephemeral_root,
        repo_mirrors_dir="/mirrors",
        purge_quarantine_dir="/quarantine",
    )


def test_invariant_purge_receipt_persisted(tmp_path):
    mock_run = create_mock_run("r_receipt_test")
    temp_ops_dir = tmp_path / "ops"
    temp_ops_dir.mkdir()
    settings = _settings(ephemeral_root="/ephemeral")

    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.purge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("tools.gimo_server.services.ops_service.OpsService._run_events_path", return_value=temp_ops_dir / "events.jsonl"), \
         patch("tools.gimo_server.services.ops_service.OpsService._run_log_path", return_value=temp_ops_dir / "logs.jsonl"), \
         patch("tools.gimo_server.services.ops_service.OpsService._run_path", return_value=temp_ops_dir / "run.json"), \
         patch("tools.gimo_server.services.ops_service.OpsService.OPS_DIR", temp_ops_dir):
        (temp_ops_dir / "run.json").write_text("{}", encoding="utf-8")
        receipt = PurgeService.purge_run("r_receipt_test")

    assert receipt.success
    receipt_path = temp_ops_dir / "purge_receipts" / f"purge_{receipt.run_id}.json"
    assert receipt_path.exists()
    content = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert content["run_id"] == "r_receipt_test"
    assert content["success"] is True
    assert "retained_metadata_hash" in content
    assert "removed_categories" in content


def test_invariant_minimal_terminal_metadata_only():
    mock_run = create_mock_run("r_meta")
    mock_run.validated_task_spec = {"secret": "reconstructive"}
    mock_run.log = [{"msg": "secret"}]
    settings = _settings()

    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.purge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("tools.gimo_server.services.ops_service.OpsService._run_path", return_value=Path("run.json")), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("pathlib.Path.write_text") as mock_write, \
         patch("tools.gimo_server.services.purge_service.PurgeService._persist_receipt"):
        PurgeService.purge_run("r_meta")

    for call in mock_write.call_args_list:
        try:
            saved = json.loads(call.args[0])
        except Exception:
            continue
        if saved.get("id") == "r_meta":
            assert "status" in saved
            assert "validated_task_spec" not in saved
            assert "log" not in saved
            return
    pytest.fail("Minimal metadata was not saved")


def test_invariant_purge_fails_closed_on_partial_cleanup():
    with patch("tools.gimo_server.services.ops_service.OpsService.get_run", side_effect=Exception("Database down")):
        with pytest.raises(PurgeExecutionError, match="Purge failed for run r1: Database down"):
            PurgeService.purge_run("r1")


def test_invariant_workspace_equals_repo_root_fails_closed():
    mock_run = create_mock_run("r_root")
    mock_run.validated_task_spec = {"workspace_path": "/repo"}
    settings = _settings(repo_root="/repo", ephemeral_root="/repo")

    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.purge_service.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_dir", return_value=True):
        with pytest.raises(LifecycleProofError, match="resolves to repo_root"):
            PurgeService.purge_run("r_root")


def test_invariant_workspace_must_stay_inside_canonical_roots():
    mock_run = create_mock_run("r_root")
    mock_run.validated_task_spec = {"workspace_path": "/unsafe/workspace"}
    settings = _settings(repo_root="/repo", ephemeral_root="/ephemeral", worktree_root="/worktrees")

    with patch("tools.gimo_server.services.review_purge_contract.get_settings", return_value=settings), \
         patch("tools.gimo_server.services.ops_service.OpsService.get_run", return_value=mock_run):
        with pytest.raises(LifecycleProofError, match="outside canonical workspace roots"):
            PurgeService.purge_run("r_root")
