from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from tools.gimo_server.ops_models import OpsApproved, OpsDraft
from tools.gimo_server.services.merge_gate_service import MergeGateService
from tools.gimo_server.services.ops_service import OpsService


def _setup_ops_dirs(tmp_path):
    OpsService.OPS_DIR = tmp_path / "ops"
    OpsService.DRAFTS_DIR = OpsService.OPS_DIR / "drafts"
    OpsService.APPROVED_DIR = OpsService.OPS_DIR / "approved"
    OpsService.RUNS_DIR = OpsService.OPS_DIR / "runs"
    OpsService.LOCKS_DIR = OpsService.OPS_DIR / "locks"
    OpsService.CONFIG_FILE = OpsService.OPS_DIR / "config.json"
    OpsService.LOCK_FILE = OpsService.OPS_DIR / ".ops.lock"
    OpsService.ensure_dirs()


def _seed_draft_and_approved(*, draft_id: str = "d1", approved_id: str = "a1", risk_score: float = 10.0):
    draft = OpsDraft(
        id=draft_id,
        prompt="p",
        context={
            "repo_context": {"target_branch": "main", "repo_id": "repoA"},
            "commit_base": "abc123",
            "risk_score": risk_score,
            "intent_effective": "SAFE_REFACTOR",
            "source_ref": "HEAD",
            "policy_decision": "allow",
            "policy_decision_id": "pd-1",
        },
        status="draft",
    )
    approved = OpsApproved(
        id=approved_id,
        draft_id=draft_id,
        prompt="p",
        content="c",
    )
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    OpsService._approved_path(approved.id).write_text(approved.model_dump_json(indent=2), encoding="utf-8")
    return draft, approved


def test_phase7_create_run_is_idempotent_by_draft_and_commit_base(tmp_path):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d1", approved_id="a1")

    run1 = OpsService.create_run(approved.id)
    run2 = OpsService.create_run(approved.id)

    assert run1.id == run2.id
    assert run1.run_key == run2.run_key


def test_phase7_merge_lock_ttl_heartbeat_and_recovery(tmp_path):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d2", approved_id="a2")
    run = OpsService.create_run(approved.id)

    lock = OpsService.acquire_merge_lock("repoA", run.id, ttl_seconds=2)
    assert lock["run_id"] == run.id

    lock2 = OpsService.heartbeat_merge_lock("repoA", run.id, ttl_seconds=2)
    assert lock2["run_id"] == run.id

    # Force stale lock
    lock_file = OpsService._merge_lock_path("repoA")
    payload = __import__("json").loads(lock_file.read_text(encoding="utf-8"))
    payload["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    lock_file.write_text(__import__("json").dumps(payload), encoding="utf-8")

    recovered = OpsService.recover_stale_lock("repoA")
    assert recovered is True


def test_phase7_merge_gate_lock_conflict_sets_merge_locked(tmp_path, monkeypatch):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d3", approved_id="a3")
    run = OpsService.create_run(approved.id)

    OpsService.acquire_merge_lock("repoA", "other_run", ttl_seconds=30)

    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "MERGE_LOCKED"


def test_phase7_merge_gate_tests_failure_sets_validation_failed_tests(tmp_path, monkeypatch):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d4", approved_id="a4")
    run = OpsService.create_run(approved.id)

    from tools.gimo_server.services import merge_gate_service as mgs

    monkeypatch.setattr(mgs.GitService, "is_worktree_clean", lambda _base: True)
    monkeypatch.setattr(mgs.GitService, "run_tests", lambda _base: (False, "tests failed"))
    monkeypatch.setattr(mgs.GitService, "run_lint_typecheck", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "dry_run_merge", lambda _b, _s, _t: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "get_head_commit", lambda _base: "abc")
    monkeypatch.setattr(mgs.GitService, "perform_merge", lambda _b, _s, _t: (True, "ok"))

    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "VALIDATION_FAILED_TESTS"


def test_phase7_merge_gate_lint_failure_sets_validation_failed_lint(tmp_path, monkeypatch):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d7", approved_id="a7")
    run = OpsService.create_run(approved.id)

    from tools.gimo_server.services import merge_gate_service as mgs

    monkeypatch.setattr(mgs.GitService, "is_worktree_clean", lambda _base: True)
    monkeypatch.setattr(mgs.GitService, "run_tests", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "run_lint_typecheck", lambda _base: (False, "lint failed"))

    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "VALIDATION_FAILED_LINT"


def test_phase7_merge_gate_dry_run_conflict_sets_merge_conflict(tmp_path, monkeypatch):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d8", approved_id="a8")
    run = OpsService.create_run(approved.id)

    from tools.gimo_server.services import merge_gate_service as mgs

    monkeypatch.setattr(mgs.GitService, "is_worktree_clean", lambda _base: True)
    monkeypatch.setattr(mgs.GitService, "run_tests", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "run_lint_typecheck", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "dry_run_merge", lambda _b, _s, _t: (False, "conflict"))

    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "MERGE_CONFLICT"


def test_phase7_merge_gate_detects_baseline_tamper(tmp_path):
    _setup_ops_dirs(tmp_path)
    draft, approved = _seed_draft_and_approved(draft_id="d5", approved_id="a5")
    draft.context["policy_hash_expected"] = "hash_a"
    draft.context["policy_hash_runtime"] = "hash_b"
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    run = OpsService.create_run(approved.id)
    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "BASELINE_TAMPER_DETECTED"


def test_phase7_merge_gate_risk_60_is_hard_block(tmp_path):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d6", approved_id="a6", risk_score=60.0)
    run = OpsService.create_run(approved.id)
    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "RISK_SCORE_TOO_HIGH"


def test_phase7_merge_gate_requires_policy_decision_id(tmp_path):
    _setup_ops_dirs(tmp_path)
    draft, approved = _seed_draft_and_approved(draft_id="d9", approved_id="a9")
    draft.context.pop("policy_decision_id", None)
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    run = OpsService.create_run(approved.id)
    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "WORKER_CRASHED_RECOVERABLE"


def test_phase7_merge_gate_policy_review_requires_human(tmp_path):
    _setup_ops_dirs(tmp_path)
    draft, approved = _seed_draft_and_approved(draft_id="d10", approved_id="a10")
    draft.context["policy_decision"] = "review"
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    run = OpsService.create_run(approved.id)
    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "HUMAN_APPROVAL_REQUIRED"


def test_phase7_merge_gate_missing_intent_requires_human(tmp_path):
    _setup_ops_dirs(tmp_path)
    draft, approved = _seed_draft_and_approved(draft_id="d11", approved_id="a11")
    draft.context.pop("intent_effective", None)
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    run = OpsService.create_run(approved.id)
    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "HUMAN_APPROVAL_REQUIRED"


def test_phase7_merge_gate_post_merge_failure_triggers_rollback(tmp_path, monkeypatch):
    _setup_ops_dirs(tmp_path)
    _, approved = _seed_draft_and_approved(draft_id="d12", approved_id="a12")
    run = OpsService.create_run(approved.id)

    from tools.gimo_server.services import merge_gate_service as mgs

    monkeypatch.setattr(mgs.GitService, "is_worktree_clean", lambda _base: True)
    monkeypatch.setattr(mgs.GitService, "run_tests", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "run_lint_typecheck", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "dry_run_merge", lambda _b, _s, _t: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "perform_merge", lambda _b, _s, _t: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "rollback_to_commit", lambda _b, _c: (True, "rollback ok"))

    calls = {"n": 0}

    def _head(_base):
        calls["n"] += 1
        if calls["n"] == 1:
            return "abc_before"
        raise RuntimeError("cannot read HEAD after merge")

    monkeypatch.setattr(mgs.GitService, "get_head_commit", _head)

    ok = asyncio.run(MergeGateService.execute_run(run.id))
    assert ok is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "ROLLBACK_EXECUTED"


def test_ops_service_list_drafts_filters_limit_offset(tmp_path):
    _setup_ops_dirs(tmp_path)

    now = datetime.now(timezone.utc)

    drafts = [
        OpsDraft(id="d_a", prompt="a", status="draft", created_at=now - timedelta(minutes=3)),
        OpsDraft(id="d_b", prompt="b", status="approved", created_at=now - timedelta(minutes=2)),
        OpsDraft(id="d_c", prompt="c", status="draft", created_at=now - timedelta(minutes=1)),
        OpsDraft(id="d_d", prompt="d", status="rejected", created_at=now),
    ]
    for item in drafts:
        OpsService._draft_path(item.id).write_text(item.model_dump_json(indent=2), encoding="utf-8")

    only_draft = OpsService.list_drafts(status="draft")
    assert [d.id for d in only_draft] == ["d_c", "d_a"]

    paged = OpsService.list_drafts(status="draft", offset=1, limit=1)
    assert [d.id for d in paged] == ["d_a"]
