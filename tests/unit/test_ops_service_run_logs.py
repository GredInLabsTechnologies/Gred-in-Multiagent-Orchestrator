import json
import time
from datetime import datetime, timedelta, timezone

from tools.gimo_server.ops_models import OpsRun
from tools.gimo_server.services.ops import OpsService


def _configure_ops_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(OpsService, "OPS_DIR", tmp_path / "ops")
    monkeypatch.setattr(OpsService, "DRAFTS_DIR", OpsService.OPS_DIR / "drafts")
    monkeypatch.setattr(OpsService, "APPROVED_DIR", OpsService.OPS_DIR / "approved")
    monkeypatch.setattr(OpsService, "RUNS_DIR", OpsService.OPS_DIR / "runs")
    monkeypatch.setattr(OpsService, "RUN_LOGS_DIR", OpsService.OPS_DIR / "run_logs")
    monkeypatch.setattr(OpsService, "LOCKS_DIR", OpsService.OPS_DIR / "locks")
    monkeypatch.setattr(OpsService, "LOCK_FILE", OpsService.OPS_DIR / ".ops.lock")
    OpsService.ensure_dirs()


def test_append_log_uses_append_only_jsonl_and_preserves_run_metadata(monkeypatch, tmp_path):
    _configure_ops_dirs(monkeypatch, tmp_path)

    run = OpsRun(
        id="r_test",
        approved_id="a_test",
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    OpsService._persist_run(run)

    OpsService.append_log("r_test", level="INFO", msg="first")
    OpsService.append_log("r_test", level="WARN", msg="second")

    run_payload = json.loads((OpsService.RUNS_DIR / "r_test.json").read_text(encoding="utf-8"))
    assert run_payload["log"] == []

    log_lines = (OpsService.RUN_LOGS_DIR / "r_test.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 2

    hydrated = OpsService.get_run("r_test")
    assert hydrated is not None
    assert len(hydrated.log) == 2
    assert hydrated.log[-1]["msg"] == "second"


def test_cleanup_old_runs_removes_run_and_associated_log(monkeypatch, tmp_path):
    _configure_ops_dirs(monkeypatch, tmp_path)

    run = OpsRun(
        id="r_old",
        approved_id="a_old",
        status="done",
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    OpsService._persist_run(run)
    OpsService._append_run_log_entry("r_old", level="INFO", msg="old log")

    run_path = OpsService.RUNS_DIR / "r_old.json"
    old_epoch = time.time() - 3600
    run_path.touch()
    (OpsService.RUN_LOGS_DIR / "r_old.jsonl").touch()
    import os

    os.utime(run_path, (old_epoch, old_epoch))

    cleaned = OpsService.cleanup_old_runs(ttl_seconds=10)

    assert cleaned == 1
    assert not run_path.exists()
    assert not (OpsService.RUN_LOGS_DIR / "r_old.jsonl").exists()
