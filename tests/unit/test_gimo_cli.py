from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import gimo as gimo_cli

runner = CliRunner()


def _seed_config(tmp_path: Path, monkeypatch) -> dict:
    monkeypatch.chdir(tmp_path)
    gimo_cli._save_config(gimo_cli._default_config())
    return yaml.safe_load((tmp_path / ".gimo" / "config.yaml").read_text(encoding="utf-8"))


def test_init_creates_workspace_scaffold(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(gimo_cli.app, ["init"], color=False)

    assert result.exit_code == 0
    assert (tmp_path / ".gimo" / "config.yaml").exists()
    assert (tmp_path / ".gimo" / "plans").is_dir()
    assert (tmp_path / ".gimo" / "history").is_dir()
    assert (tmp_path / ".gimo" / "runs").is_dir()

    config = yaml.safe_load((tmp_path / ".gimo" / "config.yaml").read_text(encoding="utf-8"))
    assert config["repository"]["name"] == tmp_path.name
    assert config["api"]["base_url"] == gimo_cli.DEFAULT_API_BASE_URL


def test_plan_persists_draft_locally(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def _fake_api_request(config, method, path, *, params=None):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return 201, {"id": "d_123", "status": "draft", "content": '{"tasks":[]}'}

    monkeypatch.setattr(gimo_cli, "_api_request", _fake_api_request)

    result = runner.invoke(gimo_cli.app, ["plan", "ship p1"], color=False)

    assert result.exit_code == 0
    assert captured == {
        "method": "POST",
        "path": "/ops/generate-plan",
        "params": {"prompt": "ship p1"},
    }
    saved = json.loads((tmp_path / ".gimo" / "plans" / "d_123.json").read_text(encoding="utf-8"))
    assert saved["id"] == "d_123"
    assert "Plan generated successfully" in result.stdout


def test_run_uses_auto_run_and_saves_backend_payload(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)
    captured: dict[str, object] = {}
    run_polls = iter(
        [
            {"id": "r_123", "status": "running", "stage": "execute"},
            {"id": "r_123", "status": "done", "stage": "merge"},
        ]
    )

    def _fake_api_request(config, method, path, *, params=None):
        del config
        if path == "/ops/drafts/d_123/approve":
            captured["method"] = method
            captured["path"] = path
            captured["params"] = params
            return 200, {
                "approved": {"id": "a_123"},
                "run": {"id": "r_123", "status": "pending"},
            }
        if path == "/ops/runs/r_123":
            return 200, next(run_polls)
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(gimo_cli, "_api_request", _fake_api_request)
    monkeypatch.setattr(gimo_cli.time, "sleep", lambda _: None)

    result = runner.invoke(gimo_cli.app, ["run", "d_123"], color=False)

    assert result.exit_code == 0
    assert captured == {
        "method": "POST",
        "path": "/ops/drafts/d_123/approve",
        "params": {"auto_run": "true"},
    }
    # File is keyed by run id (r_123), not plan id — this is the P0 contract
    saved = json.loads((tmp_path / ".gimo" / "runs" / "r_123.json").read_text(encoding="utf-8"))
    assert saved["run"]["id"] == "r_123"
    assert saved["run"]["status"] == "done"
    assert "Run started." in result.stdout


def test_status_reports_backend_summary(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)

    def _fake_api_request(config, method, path, *, params=None):
        del config, method, params
        if path == "/health":
            return 200, {"ok": True}
        if path == "/ops/operator/status":
            return 200, {
                "repo": "some_repo",
                "branch": "main",
                "dirty_files": [],
                "active_provider": "anthropic",
                "active_model": "claude-3-5",
                "backend_version": "9.9.9",
                "last_thread": "th_001",
                "last_turn": "trn_7",
                "alerts": ["Alert 1"]
            }
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(gimo_cli, "_api_request", _fake_api_request)

    result = runner.invoke(gimo_cli.app, ["status"], color=False)

    assert result.exit_code == 0
    assert "ONLINE" in result.stdout
    assert "9.9.9" in result.stdout
    assert "anthropic" in result.stdout
    assert "Alert 1" in result.stdout


def test_diff_calls_backend_and_prints_output(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def _fake_api_request(config, method, path, *, params=None):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return 200, " 1 file changed, 3 insertions(+)"

    monkeypatch.setattr(gimo_cli, "_api_request", _fake_api_request)

    result = runner.invoke(gimo_cli.app, ["diff", "--base", "main", "--head", "feature/p1"], color=False)

    assert result.exit_code == 0
    assert captured == {
        "method": "GET",
        "path": "/ops/files/diff",
        "params": {"base": "main", "head": "feature/p1"},
    }
    assert "1 file changed" in result.stdout


def test_config_updates_local_yaml(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)

    result = runner.invoke(
        gimo_cli.app,
        ["config", "--api-url", "http://localhost:9999", "--model", "gpt-5", "--budget", "25", "--verbose"],
        color=False,
    )

    assert result.exit_code == 0
    updated = yaml.safe_load((tmp_path / ".gimo" / "config.yaml").read_text(encoding="utf-8"))
    assert updated["api"]["base_url"] == "http://localhost:9999"
    assert updated["orchestrator"]["preferred_model"] == "gpt-5"
    assert updated["orchestrator"]["budget_limit_usd"] == pytest.approx(25.0)
    assert updated["orchestrator"]["verbose"] is True


def test_audit_aggregates_backend_checks(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)

    def _fake_api_request(config, method, path, *, params=None):
        del config, method, params
        if path == "/ops/observability/alerts":
            return 200, {"items": [], "count": 0}
        if path == "/ops/system/dependencies":
            return 200, {"items": [{"id": "git"}], "count": 1}
        if path == "/ui/audit":
            return 200, {"lines": ["line-1", "line-2"]}
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(gimo_cli, "_api_request", _fake_api_request)

    result = runner.invoke(gimo_cli.app, ["audit"], color=False)

    assert result.exit_code == 0
    assert "0 alerts" in result.stdout
    assert "1 dependencies" in result.stdout
    assert "line-2" in result.stdout


def test_status_json_emits_machine_readable_payload(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)

    def _fake_api_request(config, method, path, *, params=None):
        del config, method, params
        if path == "/health":
            return 200, {"ok": True}
        if path == "/ops/operator/status":
            return 200, {
                "repo": "some_repo",
                "branch": "main",
                "dirty_files": [],
                "active_provider": "openai",
                "active_model": "gpt-4o",
                "backend_version": "1.2.3",
                "last_thread": "th_x",
                "last_turn": "trn_1",
                "alerts": []
            }
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(gimo_cli, "_api_request", _fake_api_request)

    result = runner.invoke(gimo_cli.app, ["status", "--json"], color=False)

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["backend_online"] is True
    assert payload["version"] == "1.2.3"
    assert payload["repo"] == "some_repo"
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-4o"
    assert payload["alerts"] == []


def test_rollback_uses_safe_git_wrapper(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)
    calls: list[list[str]] = []

    def _cp(args: list[str], stdout: str = "", stderr: str = "", returncode: int = 0):
        return subprocess.CompletedProcess(["git", *args], returncode, stdout=stdout, stderr=stderr)

    def _fake_git_command(args: list[str]):
        calls.append(args)
        if args == ["rev-parse", "--is-inside-work-tree"]:
            return _cp(args, stdout="true\n")
        if args == ["status", "--porcelain"]:
            return _cp(args, stdout="")
        if args == ["rev-list", "--parents", "-n", "1", "HEAD"]:
            return _cp(args, stdout="abc123 def456\n")
        if args == ["revert", "--no-edit", "HEAD"]:
            return _cp(args, stdout="[main deadbeef] revert\n")
        if args == ["rev-parse", "--short", "HEAD"]:
            return _cp(args, stdout="deadbeef\n")
        raise AssertionError(f"Unexpected git args: {args}")

    monkeypatch.setattr(gimo_cli, "_git_command", _fake_git_command)

    result = runner.invoke(gimo_cli.app, ["rollback", "--yes"], color=False)

    assert result.exit_code == 0
    assert ["revert", "--no-edit", "HEAD"] in calls
    assert "Rollback completed." in result.stdout


def test_watch_json_collects_sse_events(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)

    def _fake_stream_events(config, *, path="/ops/stream", timeout_seconds=30.0):
        del config, path, timeout_seconds
        yield {"event": "run_started", "run_id": "r1"}
        yield {"event": "run_finished", "run_id": "r1", "status": "done"}

    monkeypatch.setattr(gimo_cli, "_stream_events", _fake_stream_events)

    result = runner.invoke(gimo_cli.app, ["watch", "--limit", "2", "--json"], color=False)

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload[0]["event"] == "run_started"
    assert payload[1]["status"] == "done"
