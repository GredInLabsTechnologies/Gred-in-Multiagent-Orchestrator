from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path

import httpx
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

    result_payload = {"draft_id": "d_123", "custom_plan_id": "cp_1", "task_count": 1}
    sse_lines = [
        'data: {"stage":"analyzing_prompt","progress":0.1,"message":"Analyzing..."}',
        f'data: {json.dumps({"result": result_payload, "duration": 1.2, "status": "success"})}',
    ]

    class _FakeResponse:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def iter_lines(self):
            return iter(sse_lines)

    class _FakeClient:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def stream(self, method, url, **kw):
            return _FakeResponse()

    monkeypatch.setattr("httpx.Client", _FakeClient)
    monkeypatch.setattr("gimo_cli.commands.plan.load_bond", lambda _url: {"token": "t", "role": "operator"})
    monkeypatch.setattr("gimo_cli.commands.plan.provider_config_request", lambda _cfg: (200, {"active": "test-provider"}))

    result = runner.invoke(gimo_cli.app, ["plan", "ship p1"], color=False)

    assert result.exit_code == 0
    saved = json.loads((tmp_path / ".gimo" / "plans" / "d_123.json").read_text(encoding="utf-8"))
    assert saved["draft_id"] == "d_123"
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

    def _fake_api_request(config, method, path, *, params=None, **_kwargs):
        del config
        if path == "/ops/drafts/d_123" and method == "GET":
            return 200, {"id": "d_123", "context": {}}
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

    monkeypatch.setattr("gimo_cli.commands.run.api_request", _fake_api_request)
    monkeypatch.setattr("gimo_cli.stream.api_request", _fake_api_request)
    import time as _time_mod
    monkeypatch.setattr(_time_mod, "sleep", lambda _: None)

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
    calls: list[str] = []

    def _fake_api_request(config, method, path, *, params=None):
        del config, method, params
        calls.append(path)
        if path == "/ops/operator/status":
            return 200, {
                "repo": "some_repo",
                "branch": "main",
                "dirty_files": [],
                "active_provider": "anthropic",
                "active_model": "claude-3-5",
                "backend_version": "9.9.9",
                "permissions": "suggest",
                "last_thread": "th_001",
                "last_turn": "trn_7",
                "alerts": ["Alert 1"]
            }
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr("gimo_cli.commands.core.api_request", _fake_api_request)

    result = runner.invoke(gimo_cli.app, ["status"], color=False)

    assert result.exit_code == 0
    assert calls == ["/ops/operator/status"]
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

    monkeypatch.setattr("gimo_cli.commands.ops.api_request", _fake_api_request)

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


def test_providers_login_api_key_stores_credentials_without_switching_active(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)
    calls: list[tuple[str, str, object, str]] = []

    def _fake_api_request(config, method, path, *, json_body=None, role="operator", **kwargs):
        del config, kwargs
        calls.append((method, path, json_body, role))
        if path == "/ops/provider":
            return 200, {
                "active": "openai-main",
                "providers": {
                    "openai-main": {"provider_type": "openai"},
                    "groq-main": {"provider_type": "groq"},
                },
            }
        if path == "/ops/connectors/groq-main/credentials":
            assert json_body == {"api_key": "gsk_test_1234567890"}
            return 200, {"provider_id": "groq-main", "status": "stored", "active": "openai-main"}
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr("gimo_cli.commands.providers.api_request", _fake_api_request)

    result = runner.invoke(
        gimo_cli.app,
        ["providers", "login", "groq", "--api-key", "gsk_test_1234567890"],
        color=False,
    )

    assert result.exit_code == 0
    assert calls == [
        ("GET", "/ops/provider", None, "operator"),
        ("POST", "/ops/connectors/groq-main/credentials", {"api_key": "gsk_test_1234567890"}, "operator"),
    ]
    assert "/ops/provider/select" not in result.stdout
    assert "Active provider unchanged: openai-main" in result.stdout


def test_providers_add_registers_without_activation_by_default(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def _fake_api_request(config, method, path, *, json_body=None, role="operator", **kwargs):
        del config, kwargs
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        captured["role"] = role
        return 200, {"active": "openai-main"}

    monkeypatch.setattr("gimo_cli.commands.providers.api_request", _fake_api_request)

    result = runner.invoke(
        gimo_cli.app,
        ["providers", "add", "groq-main", "--type", "groq", "--api-key", "gsk_test_1234567890"],
        color=False,
    )

    assert result.exit_code == 0
    assert captured == {
        "method": "POST",
        "path": "/ops/provider/upsert",
        "json_body": {
            "provider_id": "groq-main",
            "provider_type": "groq",
            "display_name": None,
            "base_url": None,
            "api_key": "gsk_test_1234567890",
            "model": "qwen/qwen3-32b",
            "activate": False,
        },
        "role": "admin",
    }
    assert "Provider 'groq-main' registered" in result.stdout


def test_audit_aggregates_backend_checks(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)

    def _fake_api_request(config, method, path, *, params=None):
        del config, method, params
        if path == "/ops/observability/alerts":
            return 200, {"items": [], "count": 0}
        if path == "/ops/system/dependencies":
            return 200, {"items": [{"id": "git"}], "count": 1}
        if path == "/ops/audit/tail":
            return 200, {"lines": ["line-1", "line-2"]}
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr("gimo_cli.commands.ops.api_request", _fake_api_request)

    result = runner.invoke(gimo_cli.app, ["audit"], color=False)

    assert result.exit_code == 0
    assert "0 alerts" in result.stdout
    assert "1 dependencies" in result.stdout
    assert "line-2" in result.stdout


def test_observe_traces_uses_canonical_trace_id(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def _fake_api_request(config, method, path, *, params=None):
        del config
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return 200, {
            "items": [{"trace_id": "trace-123", "status": "completed", "duration_ms": 42}],
            "count": 1,
        }

    monkeypatch.setattr("gimo_cli.commands.observe.api_request", _fake_api_request)

    result = runner.invoke(gimo_cli.app, ["observe", "traces"], color=False)

    assert result.exit_code == 0
    assert captured == {
        "method": "GET",
        "path": "/ops/observability/traces",
        "params": {"limit": 10},
    }
    assert "trace-123" in result.stdout


def test_status_json_emits_machine_readable_payload(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)
    calls: list[str] = []

    def _fake_api_request(config, method, path, *, params=None):
        del config, method, params
        calls.append(path)
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

    monkeypatch.setattr("gimo_cli.commands.core.api_request", _fake_api_request)

    result = runner.invoke(gimo_cli.app, ["status", "--json"], color=False)

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert calls == ["/ops/operator/status"]
    assert payload["backend_version"] == "1.2.3"
    assert payload["repo"] == "some_repo"
    assert payload["active_provider"] == "openai"
    assert payload["active_model"] == "gpt-4o"
    assert payload["alerts"] == []


def test_status_backend_failure_exits_without_local_fallback(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)
    git_calls: list[list[str]] = []

    def _fake_api_request(config, method, path, *, params=None):
        del config, method, params
        assert path == "/ops/operator/status"
        return 500, "backend unavailable"

    def _fake_git_command(args: list[str]):
        git_calls.append(args)
        raise AssertionError("status must not fall back to local git heuristics")

    monkeypatch.setattr("gimo_cli.commands.core.api_request", _fake_api_request)

    result = runner.invoke(gimo_cli.app, ["status"], color=False)

    assert result.exit_code == 1
    assert "Failed to fetch authoritative status" in result.stdout
    assert git_calls == []


def test_interactive_chat_done_event_does_not_render_local_notices_or_post_run_report(tmp_path, monkeypatch):
    config = _seed_config(tmp_path, monkeypatch)
    renderer_box: dict[str, object] = {}

    class FakeRenderer:
        def __init__(self, console, verbose=False):
            self.console = console
            self.verbose = verbose
            self.telemetry_html = None
            self._generation_active = False
            self.responses: list[str] = []
            self.footers: list[dict[str, object]] = []
            renderer_box["renderer"] = self

        def render_preflight_error(self, *args, **kwargs):
            raise AssertionError("preflight should pass")

        def render_session_header(self, **kwargs):
            return None

        def get_user_input(self):
            if not hasattr(self, "_inputs"):
                self._inputs = iter(["hello", "/exit"])
            return next(self._inputs)

        @contextmanager
        def render_thinking(self):
            yield

        def render_sse_raw(self, *args, **kwargs):
            return None

        def render_tool_call_start(self, *args, **kwargs):
            return None

        def render_hitl_prompt(self, *args, **kwargs):
            return False

        def render_tool_call_result(self, *args, **kwargs):
            return None

        def render_error(self, message):
            raise AssertionError(message)

        def render_user_question(self, *args, **kwargs):
            return None

        def render_plan(self, *args, **kwargs):
            return None

        def get_plan_approval(self):
            return "approve"

        def render_mood_indicator(self, *args, **kwargs):
            return None

        def render_interrupted(self):
            return None

        def render_response(self, response):
            self.responses.append(response)

        def render_footer(self, usage):
            self.footers.append(usage)

        def render_notice(self, *_args, **_kwargs):
            raise AssertionError("local notice synthesis must not run")

        def render_post_run_report(self, *_args, **_kwargs):
            raise AssertionError("non-canonical post-run rendering must not run")

    class FakeStreamResponse:
        status_code = 200
        request = object()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def iter_lines(self):
            yield "event: done"
            yield 'data: {"response":"server response","usage":{"total_tokens":13},"run":{"id":"run_1","objective":"ignored"}}'

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def stream(self, *args, **kwargs):
            return FakeStreamResponse()

    def _fake_api_request(config, method, path, *, params=None, json_body=None):
        del config, method, params, json_body
        if path == "/ops/operator/status":
            return 200, {
                "active_provider": "openai",
                "active_model": "gpt-5",
                "alerts": [],
                "budget_percentage": 100.0,
                "context_status": "10%",
            }
        if path == "/ops/threads":
            return 201, {"id": "th_123"}
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr("gimo_cli.chat.preflight_check", lambda config: (True, None))
    monkeypatch.setattr("gimo_cli.chat.chat_provider_summary", lambda config: ("openai", "gpt-5"))
    monkeypatch.setattr("gimo_cli.chat.api_request", _fake_api_request)
    import httpx as _httpx_mod
    monkeypatch.setattr(_httpx_mod, "Client", FakeClient)
    monkeypatch.setattr("gimo_cli_renderer.ChatRenderer", FakeRenderer)

    from gimo_cli.chat import interactive_chat
    interactive_chat(config)

    renderer = renderer_box["renderer"]
    assert renderer.responses == ["server response"]
    assert renderer.footers == [{"total_tokens": 13}]


def test_cli_uses_shared_slash_command_authority(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)

    with monkeypatch.context() as m:
        dispatch_calls: list[tuple[str, str]] = []

        def _fake_dispatch(command, argument, callbacks):
            dispatch_calls.append((command, argument))
            return True, None

        m.setattr("gimo_cli.chat.dispatch_slash_command", _fake_dispatch)
        from gimo_cli.chat import handle_chat_slash_command
        handled, outcome = handle_chat_slash_command(
            gimo_cli._load_config(),
            "/status",
            workspace_root=str(tmp_path),
            thread_id="th_123",
            renderer=None,
        )

    assert handled is True
    assert outcome is None
    assert dispatch_calls == [("/status", "")]


def test_repos_select_is_removed_from_canonical_terminal_flow(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)
    requested = tmp_path / "other-repo"
    requested.mkdir()

    def _fail_api_request(*_args, **_kwargs):
        raise AssertionError("legacy /ops/repos/select must not be called")

    monkeypatch.setattr(gimo_cli, "_api_request", _fail_api_request)

    result = runner.invoke(gimo_cli.app, ["repos", "select", str(requested)], color=False)

    assert result.exit_code == 1
    assert "Legacy host-path repo selection has been removed" in result.stdout
    assert "gimo init" in result.stdout


def test_repos_select_json_reports_canonical_replacement(tmp_path, monkeypatch):
    _seed_config(tmp_path, monkeypatch)
    requested = tmp_path / "other-repo"
    requested.mkdir()

    def _fail_api_request(*_args, **_kwargs):
        raise AssertionError("legacy /ops/repos/select must not be called")

    monkeypatch.setattr(gimo_cli, "_api_request", _fail_api_request)

    result = runner.invoke(gimo_cli.app, ["repos", "select", str(requested), "--json"], color=False)

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "legacy_removed"
    assert payload["requested_path"] == str(requested.resolve())
    assert payload["canonical_flow"]["command"] == "gimo init"


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

    monkeypatch.setattr("gimo_cli.commands.ops.git_command", _fake_git_command)

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

    monkeypatch.setattr("gimo_cli.commands.run.stream_events", _fake_stream_events)

    result = runner.invoke(gimo_cli.app, ["watch", "--limit", "2", "--json"], color=False)

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload[0]["event"] == "run_started"
    assert payload[1]["status"] == "done"


def test_stream_events_uses_requested_read_timeout(tmp_path, monkeypatch):
    config = _seed_config(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): return None
        def iter_lines(self):
            raise httpx.ReadTimeout("idle")

    class _FakeClient:
        def __init__(self, **kwargs):
            captured["timeout"] = kwargs["timeout"]
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr("gimo_cli.stream.httpx.Client", _FakeClient)
    monkeypatch.setattr("gimo_cli.stream.resolve_token", lambda _role, _config: None)

    assert list(gimo_cli._stream_events(config, timeout_seconds=5)) == []
    assert captured["timeout"].read == 5


def test_stream_events_treats_keepalive_only_stream_as_idle(tmp_path, monkeypatch):
    config = _seed_config(tmp_path, monkeypatch)
    messages: list[str] = []
    ticks = iter([0.0, 1.0, 2.0, 3.0, 6.1])

    class _FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): return None
        def iter_lines(self):
            yield ": keep-alive"
            yield ": keep-alive"
            yield ": keep-alive"
            yield ": keep-alive"

    class _FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr("gimo_cli.stream.httpx.Client", _FakeClient)
    monkeypatch.setattr("gimo_cli.stream.resolve_token", lambda _role, _config: None)
    monkeypatch.setattr("gimo_cli.stream.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("gimo_cli.stream.console.print", lambda message: messages.append(str(message)))

    assert list(gimo_cli._stream_events(config, timeout_seconds=5)) == []
    assert messages == ["[yellow]No events received for 5s - stream idle.[/yellow]"]
