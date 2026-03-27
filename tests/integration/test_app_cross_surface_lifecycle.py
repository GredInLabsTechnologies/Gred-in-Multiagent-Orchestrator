from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tools.gimo_server.config import get_settings
from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.ops_service import OpsService


def _override_auth() -> AuthContext:
    return AuthContext(token="test-token", role="operator")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _configure_ops_dirs(monkeypatch, tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    monkeypatch.setattr(OpsService, "OPS_DIR", ops_dir)
    monkeypatch.setattr(OpsService, "PLAN_FILE", ops_dir / "plan.json")
    monkeypatch.setattr(OpsService, "PROVIDER_FILE", ops_dir / "provider.json")
    monkeypatch.setattr(OpsService, "DRAFTS_DIR", ops_dir / "drafts")
    monkeypatch.setattr(OpsService, "APPROVED_DIR", ops_dir / "approved")
    monkeypatch.setattr(OpsService, "RUNS_DIR", ops_dir / "runs")
    monkeypatch.setattr(OpsService, "RUN_EVENTS_DIR", ops_dir / "run_events")
    monkeypatch.setattr(OpsService, "RUN_LOGS_DIR", ops_dir / "run_logs")
    monkeypatch.setattr(OpsService, "LOCKS_DIR", ops_dir / "locks")
    monkeypatch.setattr(OpsService, "CONFIG_FILE", ops_dir / "config.json")
    monkeypatch.setattr(OpsService, "LOCK_FILE", ops_dir / ".ops.lock")
    OpsService.ensure_dirs()


def _configure_surface_settings(monkeypatch, tmp_path: Path):
    from tools.gimo_server import config as config_mod
    from tools.gimo_server.services import app_session_service, purge_service, review_purge_contract, sandbox_service

    base_settings = get_settings()
    test_settings = replace(
        base_settings,
        repo_root_dir=(tmp_path / "repo_root").resolve(),
        repo_registry_path=(tmp_path / "repo_registry.json").resolve(),
        app_sessions_dir=(tmp_path / "app_sessions").resolve(),
        ephemeral_repos_dir=(tmp_path / "ephemeral_repos").resolve(),
        repo_mirrors_dir=(tmp_path / "repo_mirrors").resolve(),
        purge_quarantine_dir=(tmp_path / "purge_quarantine").resolve(),
        worktrees_dir=(tmp_path / "worktrees").resolve(),
    )

    test_settings.repo_root_dir.mkdir(parents=True, exist_ok=True)
    test_settings.app_sessions_dir.mkdir(parents=True, exist_ok=True)
    test_settings.ephemeral_repos_dir.mkdir(parents=True, exist_ok=True)
    test_settings.repo_mirrors_dir.mkdir(parents=True, exist_ok=True)
    test_settings.purge_quarantine_dir.mkdir(parents=True, exist_ok=True)
    test_settings.worktrees_dir.mkdir(parents=True, exist_ok=True)
    test_settings.repo_registry_path.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config_mod, "get_settings", lambda: test_settings)
    monkeypatch.setattr(app_session_service, "get_settings", lambda: test_settings)
    monkeypatch.setattr(sandbox_service, "get_settings", lambda: test_settings)
    monkeypatch.setattr(purge_service, "get_settings", lambda: test_settings)
    monkeypatch.setattr(review_purge_contract, "get_settings", lambda: test_settings)
    return test_settings


def test_app_surface_uses_bound_snapshot_and_closes_cross_surface_lifecycle(monkeypatch, tmp_path: Path):
    _configure_ops_dirs(monkeypatch, tmp_path)
    settings = _configure_surface_settings(monkeypatch, tmp_path)

    source_repo = tmp_path / "source_repo"
    source_repo.mkdir()
    _git(source_repo, "init")
    _git(source_repo, "config", "user.name", "Tester")
    _git(source_repo, "config", "user.email", "tester@example.com")
    (source_repo / "app.py").write_text("print('v1')\n", encoding="utf-8")
    _git(source_repo, "add", "app.py")
    _git(source_repo, "commit", "-m", "init")
    base_commit = _git(source_repo, "rev-parse", "HEAD")

    settings.repo_registry_path.write_text(
        json.dumps({"repos": [str(source_repo.resolve())]}, indent=2),
        encoding="utf-8",
    )

    queued: list[object] = []

    def _capture_task(coro):
        queued.append(coro)
        return None

    app.dependency_overrides[verify_token] = _override_auth

    with TestClient(app, raise_server_exceptions=False) as client:
        repos_res = client.get("/ops/app/repos")
        assert repos_res.status_code == 200
        repos = repos_res.json()
        assert len(repos) == 1
        repo_id = repos[0]["repo_id"]

        create_session_res = client.post("/ops/app/sessions", json={"metadata": {"surface_test": "app"}})
        assert create_session_res.status_code == 200
        session_id = create_session_res.json()["id"]

        bind_res = client.post(
            f"/ops/app/sessions/{session_id}/repo/select",
            json={"repo_id": repo_id},
        )
        assert bind_res.status_code == 200

        bound_snapshot = settings.app_sessions_dir / "_repos" / session_id
        assert bound_snapshot.exists()
        assert bound_snapshot.resolve() != source_repo.resolve()

        (source_repo / "app.py").write_text("print('v2')\n", encoding="utf-8")
        (source_repo / "later.py").write_text("print('later')\n", encoding="utf-8")
        _git(source_repo, "add", "app.py", "later.py")
        _git(source_repo, "commit", "-m", "source drift")
        drifted_head = _git(source_repo, "rev-parse", "HEAD")
        assert drifted_head != base_commit

        list_res = client.get(f"/ops/app/sessions/{session_id}/recon/list")
        assert list_res.status_code == 200
        entries = list_res.json()
        assert [entry["name"] for entry in entries] == ["app.py"]

        app_handle = entries[0]["handle"]
        read_res = client.get(f"/ops/app/sessions/{session_id}/recon/read/{app_handle}")
        assert read_res.status_code == 200
        read_payload = read_res.json()
        assert read_payload["content"] == "print('v1')\n"
        assert read_payload["proof"]["base_commit"] == base_commit

        draft_res = client.post(
            f"/ops/app/sessions/{session_id}/drafts",
            json={
                "acceptance_criteria": "Update app.py without leaving the approved scope.",
                "allowed_paths": ["app.py"],
            },
        )
        assert draft_res.status_code == 200
        draft_payload = draft_res.json()
        draft_id = draft_payload["draft_id"]
        assert draft_payload["validated_task_spec"]["repo_handle"] == repo_id
        assert draft_payload["repo_context_pack"]["session_id"] == session_id

        approve_res = client.post(f"/ops/drafts/{draft_id}/approve")
        assert approve_res.status_code == 200
        approved_id = approve_res.json()["approved"]["id"]
        assert approve_res.json()["run"] is None

        with patch("tools.gimo_server.routers.ops.run_router.asyncio.create_task", side_effect=_capture_task):
            create_run_res = client.post("/ops/runs", json={"approved_id": approved_id})

        assert create_run_res.status_code == 201
        run_payload = create_run_res.json()
        run_id = run_payload["id"]
        assert run_payload["status"] == "running"
        assert len(queued) == 1

        workspace_path = Path(run_payload["validated_task_spec"]["workspace_path"])
        assert workspace_path.exists()
        assert workspace_path.is_relative_to(settings.ephemeral_repos_dir)
        assert workspace_path.resolve() != source_repo.resolve()
        assert workspace_path.resolve() != bound_snapshot.resolve()

        (workspace_path / "app.py").write_text("print('workspace change')\n", encoding="utf-8")

        review_res = client.get(f"/ops/app/runs/{run_id}/review")
        assert review_res.status_code == 200
        review_payload = review_res.json()
        assert review_payload["preview"]["drift_detected"] is False
        assert review_payload["preview"]["expected_base"] == base_commit
        assert review_payload["preview"]["source_repo_head"] == base_commit
        assert review_payload["preview"]["source_repo_head"] != drifted_head
        assert "app.py" in review_payload["bundle"]["changed_files"]
        assert "workspace change" in review_payload["bundle"]["diff_summary"]

        discard_res = client.post(f"/ops/app/runs/{run_id}/discard")
        assert discard_res.status_code == 200
        receipt = discard_res.json()["receipt"]
        assert receipt["success"] is True
        assert "workspace" in receipt["removed_categories"]
        assert "events" in receipt["removed_categories"]
        assert "logs" in receipt["removed_categories"]

        purge_receipt_path = OpsService.OPS_DIR / "purge_receipts" / f"purge_{run_id}.json"
        assert purge_receipt_path.exists()
        run_path = OpsService._run_path(run_id)
        purged_run = json.loads(run_path.read_text(encoding="utf-8"))
        assert purged_run["purged"] is True
        assert "validated_task_spec" not in purged_run
        assert workspace_path.exists() is False

        purge_session_res = client.post(f"/ops/app/sessions/{session_id}/purge")
        assert purge_session_res.status_code == 200
        assert bound_snapshot.exists() is False

    while queued:
        queued.pop().close()
