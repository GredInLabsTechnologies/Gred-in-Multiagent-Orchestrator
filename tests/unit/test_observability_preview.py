from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.gimo_server.ops_models import OpsApproved, OpsDraft
from tools.gimo_server.services.observability_pkg.observability_service import ObservabilityService
from tools.gimo_server.services.ops import OpsService


def _setup_ops_dirs(tmp_path):
    OpsService.OPS_DIR = tmp_path / "ops"
    OpsService.DRAFTS_DIR = OpsService.OPS_DIR / "drafts"
    OpsService.APPROVED_DIR = OpsService.OPS_DIR / "approved"
    OpsService.RUNS_DIR = OpsService.OPS_DIR / "runs"
    OpsService.LOCKS_DIR = OpsService.OPS_DIR / "locks"
    OpsService.CONFIG_FILE = OpsService.OPS_DIR / "config.json"
    OpsService.LOCK_FILE = OpsService.OPS_DIR / ".ops.lock"
    OpsService.ensure_dirs()


def _seed_run(tmp_path) -> str:
    _setup_ops_dirs(tmp_path)
    draft = OpsDraft(
        id="d_phase8",
        prompt="phase8",
        context={
            "repo_context": {"target_branch": "main", "repo_id": "repoA"},
            "commit_base": "abc123",
            "risk_score": 12.0,
            "intent_declared": "SAFE_REFACTOR",
            "intent_effective": "SAFE_REFACTOR",
            "execution_decision": "AUTO_RUN_ELIGIBLE",
            "policy_hash_expected": "h_expected",
            "policy_hash_runtime": "h_runtime",
            "baseline_version": "v1",
            "fallback_used": False,
            "model_attempted": "qwen3-coder:480b-cloud",
            "final_model_used": "qwen3-coder:480b-cloud",
        },
        status="draft",
    )
    approved = OpsApproved(
        id="a_phase8",
        draft_id=draft.id,
        prompt=draft.prompt,
        content="content",
    )
    OpsService._draft_path(draft.id).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    OpsService._approved_path(approved.id).write_text(approved.model_dump_json(indent=2), encoding="utf-8")
    run = OpsService.create_run(approved.id)
    OpsService.update_run_merge_metadata(run.id, commit_before="c_before", commit_after="c_after")
    return run.id


def test_phase8_preview_contract_and_correlation(test_client, valid_token, tmp_path):
    run_id = _seed_run(tmp_path)

    response = test_client.get(
        f"/ops/runs/{run_id}/preview",
        headers={
            "Authorization": f"Bearer {valid_token}",
            "X-Request-ID": "req-phase8-1",
            "X-Trace-ID": "trace-phase8-1",
        },
    )
    assert response.status_code == 200
    payload = response.json()

    # Campos obligatorios Fase 8
    required = {
        "diff_summary",
        "risk_score",
        "model_used",
        "policy_hash_expected",
        "policy_hash_runtime",
        "baseline_version",
        "commit_before",
        "commit_after",
    }
    for key in required:
        assert key in payload

    # Correlación obligatoria
    assert payload["run_id"] == run_id
    assert payload["request_id"] == "req-phase8-1"
    assert payload["trace_id"] == "trace-phase8-1"
    # No secretos en preview
    forbidden_keys = {"api_key", "token", "refresh_token", "auth_ref"}
    assert forbidden_keys.isdisjoint(set(payload.keys()))


def test_phase8_request_id_header_is_echoed(test_client, valid_token):
    response = test_client.get(
        "/status",
        headers={
            "Authorization": f"Bearer {valid_token}",
            "X-Request-ID": "req-echo-1",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "req-echo-1"


def test_phase8_metrics_include_required_rates_and_categories():
    ObservabilityService.reset()
    ObservabilityService.record_structured_event(
        event_type="run_preview_read",
        status="FALLBACK_MODEL_USED",
        trace_id="t1",
        request_id="r1",
        run_id="run1",
        stage="preview",
        latency_ms=10,
        error_category="",
    )
    ObservabilityService.record_structured_event(
        event_type="policy_block",
        status="BASELINE_TAMPER_DETECTED",
        trace_id="t2",
        request_id="r2",
        run_id="run2",
        stage="policy",
        latency_ms=5,
        error_category="baseline",
    )

    metrics = ObservabilityService.get_metrics()
    assert "latency_ms_by_stage" in metrics
    assert "fallback_rate" in metrics
    assert "human_approval_required_rate" in metrics
    assert "policy_block_rate" in metrics
    assert "errors_by_category" in metrics
    assert "baseline" in metrics["errors_by_category"]


def test_phase8_alerts_endpoint_exposes_sev0_sev1(test_client, valid_token):
    ObservabilityService.reset()
    ObservabilityService.record_structured_event(
        event_type="policy_block",
        status="BASELINE_TAMPER_DETECTED",
        trace_id="t-sev0",
        request_id="r-sev0",
        run_id="run-sev0",
        stage="policy",
        latency_ms=1,
        error_category="baseline",
    )
    # Force a high fallback rate for SEV-1 threshold
    ObservabilityService.record_structured_event(
        event_type="run_preview_read",
        status="FALLBACK_MODEL_USED",
        trace_id="t-sev1",
        request_id="r-sev1",
        run_id="run-sev1",
        stage="preview",
        latency_ms=1,
        error_category="",
    )

    response = test_client.get(
        "/ops/observability/alerts",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    codes = {item.get("code") for item in payload["items"]}
    assert "BASELINE_TAMPER_DETECTED" in codes
    assert "HIGH_FALLBACK_RATE" in codes


def test_phase8_metrics_detect_stuck_runs(monkeypatch):
    ObservabilityService.reset()

    now = datetime.now(timezone.utc)
    active_stuck = {
        "id": "r_stuck",
        "status": "running",
        "created_at": now - timedelta(hours=2),
        "started_at": now - timedelta(hours=2),
        "heartbeat_at": now - timedelta(hours=2),
    }
    terminal_done = {
        "id": "r_done",
        "status": "done",
        "created_at": now - timedelta(minutes=30),
        "started_at": now - timedelta(minutes=25),
        "heartbeat_at": now - timedelta(minutes=20),
    }

    class _Run:
        def __init__(self, data):
            self.id = data["id"]
            self.status = data["status"]
            self.created_at = data["created_at"]
            self.started_at = data["started_at"]
            self.heartbeat_at = data["heartbeat_at"]

    monkeypatch.setattr(OpsService, "list_runs", lambda: [_Run(active_stuck), _Run(terminal_done)])

    metrics = ObservabilityService.get_metrics()
    assert metrics["active_runs"] == 1
    assert metrics["terminal_runs"] == 1
    assert metrics["stuck_runs"] == 1
    assert "r_stuck" in metrics["stuck_run_ids"]

    alerts = ObservabilityService.get_alerts()
    assert any(a.get("code") == "STUCK_RUN_DETECTED" for a in alerts)
