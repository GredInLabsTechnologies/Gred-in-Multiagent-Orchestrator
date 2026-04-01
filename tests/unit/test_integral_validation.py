from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from tools.gimo_server.main import app
from tools.gimo_server.ops_models import OpsApproved, OpsDraft, PolicyDecision
from tools.gimo_server.routers.ops import plan_router
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.merge_gate_service import MergeGateService
from tools.gimo_server.services.model_router_service import ModelRouterService
from tools.gimo_server.services.ops_service import OpsService
from tools.gimo_server.services.provider_service import ProviderService
from tools.gimo_server.services.repo_override_service import RepoOverrideService
from tools.gimo_server.services.runtime_policy_service import RuntimePolicyService


def _override_admin() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


def _setup_ops_dirs(tmp_path):
    OpsService.OPS_DIR = tmp_path / "ops"
    OpsService.DRAFTS_DIR = OpsService.OPS_DIR / "drafts"
    OpsService.APPROVED_DIR = OpsService.OPS_DIR / "approved"
    OpsService.RUNS_DIR = OpsService.OPS_DIR / "runs"
    OpsService.LOCKS_DIR = OpsService.OPS_DIR / "locks"
    OpsService.CONFIG_FILE = OpsService.OPS_DIR / "config.json"
    OpsService.LOCK_FILE = OpsService.OPS_DIR / ".ops.lock"
    OpsService.ensure_dirs()


def _seed_draft_and_approved(tmp_path, draft_id: str = "d10", approved_id: str = "a10"):
    _setup_ops_dirs(tmp_path)
    draft = OpsDraft(
        id=draft_id,
        prompt="phase10",
        context={
            "repo_context": {"target_branch": "main", "repo_id": "repo_phase10"},
            "commit_base": "abc123",
            "risk_score": 10.0,
            "intent_effective": "SAFE_REFACTOR",
            "source_ref": "HEAD",
            "policy_decision": "allow",
            "policy_decision_id": "pd-10",
            "execution_decision": "AUTO_RUN_ELIGIBLE",
            "policy_hash_expected": "h_same",
            "policy_hash_runtime": "h_same",
        },
        status="draft",
    )
    approved = OpsApproved(
        id=approved_id,
        draft_id=draft_id,
        prompt="phase10",
        content="ok",
    )
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    OpsService._approved_path(approved.id).write_text(approved.model_dump_json(indent=2), encoding="utf-8")
    return draft, approved


def test_phase10_forbidden_path_rejected(monkeypatch):
    app.dependency_overrides[verify_token] = _override_admin
    monkeypatch.setattr(
        plan_router.RuntimePolicyService,
        "evaluate_draft_policy",
        lambda **_: PolicyDecision(
            policy_decision_id="pd10-1",
            decision="deny",
            status_code="DRAFT_REJECTED_FORBIDDEN_SCOPE",
            policy_hash_expected="h1",
            policy_hash_runtime="h1",
            triggered_rules=["forbidden_path:tools/gimo_server/security/auth.py"],
        ),
    )
    body = {
        "objective": "No tocar security",
        "constraints": ["scope estricto"],
        "acceptance_criteria": ["rechazo auditable"],
        "repo_context": {
            "target_branch": "main",
            "path_scope": ["tools/gimo_server/security/auth.py"],
        },
        "execution": {"intent_class": "SAFE_REFACTOR", "risk_score": 10},
    }
    try:
        with __import__("fastapi.testclient").testclient.TestClient(app) as client:
            res = client.post("/ops/drafts", json=body)
            assert res.status_code == 201
            payload = res.json()
            assert payload["status"] == "rejected"
            assert payload["error"] == "DRAFT_REJECTED_FORBIDDEN_SCOPE"
    finally:
        app.dependency_overrides.clear()


def test_phase10_improper_auto_run_forced_human_approval(monkeypatch):
    app.dependency_overrides[verify_token] = _override_admin
    from tools.gimo_server.routers.ops import run_router

    draft = OpsDraft(
        id="d10_human",
        prompt="p",
        context={"execution_decision": "HUMAN_APPROVAL_REQUIRED"},
        status="draft",
    )
    approved = OpsApproved(id="a10_human", draft_id=draft.id, prompt="p", content="c")
    monkeypatch.setattr(run_router.OpsService, "get_draft", lambda _id: draft)
    monkeypatch.setattr(run_router.OpsService, "approve_draft", lambda *_a, **_k: approved)

    def _raise_assertion(*args, **kwargs):
        raise AssertionError("must not auto-run")

    monkeypatch.setattr(run_router.OpsService, "create_run", _raise_assertion)
    try:
        with __import__("fastapi.testclient").testclient.TestClient(app) as client:
            res = client.post(f"/ops/drafts/{draft.id}/approve?auto_run=true")
            assert res.status_code == 200
            assert res.json().get("run") is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_phase10_cloud_failure_triggers_local_fallback(monkeypatch):
    import httpx

    req = httpx.Request("POST", "http://localhost/v1/chat/completions")
    resp = httpx.Response(429, request=req)

    async def _fake_generate(_prompt, _ctx):
        raise httpx.HTTPStatusError("too many requests", request=req, response=resp)

    calls = {"n": 0}

    async def _fallback_ok(prompt, ctx):
        calls["n"] += 1
        if calls["n"] <= 2:
            return await _fake_generate(prompt, ctx)
        return {"provider": "local_ollama", "model": "qwen3:8b", "content": "ok", "tokens_used": 1, "cost_usd": 0.0}

    monkeypatch.setattr(ProviderService, "static_generate", _fallback_ok)
    result = await ProviderService.static_generate_phase6_strategy(
        prompt="phase10",
        context={},
        intent_effective="SAFE_REFACTOR",
        path_scope=["tools/gimo_server/services/ops_service.py"],
    )
    assert result["fallback_used"] is True
    assert result["execution_decision"] == "FALLBACK_MODEL_USED"


@pytest.mark.asyncio
async def test_phase10_both_models_fail_returns_clean_error(monkeypatch):
    import httpx

    req = httpx.Request("POST", "http://localhost/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    calls = {"n": 0}

    async def _all_fail(_prompt, _ctx):
        await asyncio.sleep(0)
        calls["n"] += 1
        if calls["n"] <= 2:
            raise httpx.HTTPStatusError("too many requests", request=req, response=resp)
        raise RuntimeError("local provider unavailable")

    monkeypatch.setattr(ProviderService, "static_generate", _all_fail)
    with pytest.raises(RuntimeError) as exc:
        await ProviderService.static_generate_phase6_strategy(
            prompt="phase10",
            context={},
            intent_effective="SAFE_REFACTOR",
            path_scope=["tools/gimo_server/services/ops_service.py"],
        )
    message = str(exc.value)
    assert "PHASE6_FALLBACK_FAILED:429" in message
    assert "tools/gimo_server" not in message
    assert "traceback" not in message.lower()


@pytest.mark.asyncio
async def test_phase10_account_mode_token_expired_during_critical_execution(monkeypatch):
    calls = {"n": 0}

    async def _auth_expired_then_local_ok(_prompt, _ctx):
        await asyncio.sleep(0)
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("PROVIDER_AUTH_EXPIRED")
        return {"provider": "local_ollama", "model": "qwen3:8b", "content": "ok", "tokens_used": 1, "cost_usd": 0.0}

    monkeypatch.setattr(ProviderService, "static_generate", _auth_expired_then_local_ok)
    result = await ProviderService.static_generate_phase6_strategy(
        prompt="phase10-auth-expired",
        context={"auth_mode": "account"},
        intent_effective="SAFE_REFACTOR",
        path_scope=["tools/gimo_server/services/provider_service.py"],
    )
    assert result["fallback_used"] is True
    assert result["execution_decision"] == "FALLBACK_MODEL_USED"
    assert result["failure_reason"] == "provider_auth_expired"


def test_phase10_merge_conflict_main_intact(tmp_path, monkeypatch):
    _, approved = _seed_draft_and_approved(tmp_path, draft_id="d10_merge", approved_id="a10_merge")
    run = OpsService.create_run(approved.id)
    from tools.gimo_server.services import merge_gate_service as mgs

    # Provide workspace/authoritative paths to satisfy resolve_* functions
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mgs, "resolve_workspace_path", lambda *a, **kw: workspace)
    monkeypatch.setattr(mgs, "resolve_authoritative_repo_path", lambda *a, **kw: workspace)
    monkeypatch.setattr(mgs.GitService, "is_worktree_clean", lambda _base: True)
    monkeypatch.setattr(mgs.GitService, "run_tests", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "run_lint_typecheck", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "dry_run_merge", lambda _b, _s, _t: (False, "conflict"))

    assert asyncio.run(MergeGateService.execute_run(run.id)) is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "MERGE_CONFLICT"
    assert updated.commit_before is None
    assert updated.commit_after is None


def test_phase10_restart_keeps_override(tmp_path, monkeypatch):
    override_path = tmp_path / "state" / "active_repo.json"
    monkeypatch.setattr(RepoOverrideService, "OVERRIDE_PATH", override_path)
    created = RepoOverrideService.set_human_override(repo_id=str(tmp_path / "repoA"), set_by_user="operator")
    before = RepoOverrideService.get_active_override()
    # Simulated restart: same persisted file, same service class re-read.
    after = RepoOverrideService.get_active_override()
    assert before is not None and after is not None
    assert before["repo_id"] == after["repo_id"]
    assert created["etag"] == after["etag"]


def test_phase10_policy_modification_detected_as_baseline_tamper(tmp_path, monkeypatch):
    policy_path = tmp_path / "state" / "policy.json"
    baseline_path = tmp_path / "runtime" / "baseline_manifest.json"
    monkeypatch.setattr(RuntimePolicyService, "POLICY_PATH", policy_path)
    monkeypatch.setattr(RuntimePolicyService, "BASELINE_PATH", baseline_path)

    RuntimePolicyService.ensure_runtime_files()
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    payload["forbidden_paths"] = ["tools/gimo_server/security"]
    policy_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    decision = RuntimePolicyService.evaluate_draft_policy(path_scope=["tools/gimo_server/services/ops_service.py"])
    assert decision.status_code == "BASELINE_TAMPER_DETECTED"


def test_phase10_stuck_merge_lock_recovery_controlled(tmp_path):
    _setup_ops_dirs(tmp_path)
    now = datetime.now(timezone.utc)
    lock_file = OpsService._merge_lock_path("repo-stuck")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(
        json.dumps(
            {
                "lock_id": "ml_stale",
                "repo_id": "repo-stuck",
                "run_id": "other-run",
                "acquired_at": now.isoformat(),
                "heartbeat_at": now.isoformat(),
                "expires_at": (now - timedelta(seconds=1)).isoformat(),
                "ttl_seconds": 120,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    assert OpsService.recover_stale_lock("repo-stuck") is True
    payload = OpsService.acquire_merge_lock("repo-stuck", "run-new", ttl_seconds=30)
    assert payload["run_id"] == "run-new"


def test_phase10_worker_crash_during_merge_or_rollback_is_recoverable(tmp_path, monkeypatch):
    _, approved = _seed_draft_and_approved(tmp_path, draft_id="d10_crash", approved_id="a10_crash")
    run = OpsService.create_run(approved.id)
    from tools.gimo_server.services import merge_gate_service as mgs

    monkeypatch.setattr(mgs.GitService, "is_worktree_clean", lambda _base: True)
    monkeypatch.setattr(mgs.GitService, "run_tests", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "run_lint_typecheck", lambda _base: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "dry_run_merge", lambda _b, _s, _t: (True, "ok"))
    monkeypatch.setattr(mgs.GitService, "get_head_commit", lambda _base: "head_before")

    def _raise_runtime(*args, **kwargs):
        raise RuntimeError("merge crashed")

    monkeypatch.setattr(mgs.GitService, "perform_merge", _raise_runtime)

    assert asyncio.run(MergeGateService.execute_run(run.id)) is True
    updated = OpsService.get_run(run.id)
    assert updated is not None
    assert updated.status == "WORKER_CRASHED_RECOVERABLE"


def test_phase10_override_concurrent_etag_mismatch_returns_409_style_error(tmp_path, monkeypatch):
    override_path = tmp_path / "state" / "active_repo.json"
    monkeypatch.setattr(RepoOverrideService, "OVERRIDE_PATH", override_path)
    current = RepoOverrideService.set_human_override(repo_id=str(tmp_path / "repoA"), set_by_user="operator")
    with pytest.raises(ValueError) as exc:
        RepoOverrideService.set_human_override(
            repo_id=str(tmp_path / "repoB"),
            set_by_user="operator",
            if_match_etag='"bad-etag"',
        )
    assert str(exc.value) == "OVERRIDE_ETAG_MISMATCH"
    # sanity: still can update with correct ETag
    updated = RepoOverrideService.set_human_override(
        repo_id=str(tmp_path / "repoB"),
        set_by_user="operator",
        if_match_etag=current["etag"],
    )
    assert updated["repo_id"].endswith("repoB")


def test_phase10_malformed_actions_payload_is_sanitized(test_client):
    app.dependency_overrides[verify_token] = _override_admin
    try:
        response = test_client.post(
            "/ops/drafts",
            json={"objective": 123, "execution": {"intent_class": "SAFE_REFACTOR"}},
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 422
        body = response.json()
        assert body.get("detail") == "Invalid request payload."
        serialized = str(body).lower()
        assert "traceback" not in serialized
        assert "tools/gimo_server" not in serialized
    finally:
        app.dependency_overrides.clear()
