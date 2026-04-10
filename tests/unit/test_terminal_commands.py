from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any, Callable

import pytest

from cli_commands import dispatch_slash_command
from terminal_command_executor import (
    TerminalCommandContext,
    build_terminal_command_callbacks,
)


@dataclass
class FakeSurface:
    rendered: list[Any]
    messages: list[str]
    confirmations: list[str]
    status_snapshots: list[dict[str, Any]]
    usage_snapshots: list[dict[str, Any]]
    debug_enabled: bool = False

    def render(self, renderable: Any) -> None:
        self.rendered.append(renderable)

    def render_message(self, message: str) -> None:
        self.messages.append(message)

    def clear_view(self) -> None:
        self.messages.append("CLEARED")

    def confirm(
        self,
        prompt: str,
        on_confirm: Callable[[], Any],
        *,
        cancel_message: str,
    ) -> Any:
        self.confirmations.append(prompt)
        return on_confirm()

    def get_debug(self) -> bool:
        return self.debug_enabled

    def set_debug(self, value: bool) -> None:
        self.debug_enabled = value

    def render_status_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.status_snapshots.append(snapshot)

    def render_usage_snapshot(self, usage: dict[str, Any]) -> None:
        self.usage_snapshots.append(usage)


def _context(
    api_request: Callable[..., tuple[int, Any]],
    *,
    thread_id: str = "thread-123",
    config: dict[str, Any] | None = None,
    save_calls: list[dict[str, Any]] | None = None,
) -> TerminalCommandContext:
    saved = save_calls if save_calls is not None else []
    return TerminalCommandContext(
        config=config or {"orchestrator": {}},
        workspace_root="C:/workspace",
        thread_id=thread_id,
        api_request=api_request,
        save_config=lambda cfg: saved.append(cfg.copy()),
        git_command=lambda args: subprocess.CompletedProcess(["git", *args], 0, stdout="", stderr=""),
    )


def _surface() -> FakeSurface:
    return FakeSurface([], [], [], [], [])


def test_shared_executor_status_uses_only_authoritative_snapshot():
    calls: list[tuple[str, str]] = []
    snapshot = {"repo": "repo", "branch": "main", "active_provider": "openai", "active_model": "gpt-5", "alerts": []}

    def api_request(config, method, path, **kwargs):
        del config, kwargs
        calls.append((method, path))
        return 200, snapshot

    surface = _surface()
    callbacks = build_terminal_command_callbacks(_context(api_request), surface)

    handled, _ = dispatch_slash_command("/status", "", callbacks)

    assert handled is True
    assert calls == [("GET", "/ops/operator/status")]
    assert surface.status_snapshots == [snapshot]


def test_shared_executor_tokens_reads_thread_usage_contract_only():
    calls: list[tuple[str, str]] = []
    usage = {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}

    def api_request(config, method, path, **kwargs):
        del config, kwargs
        calls.append((method, path))
        return 200, usage

    surface = _surface()
    callbacks = build_terminal_command_callbacks(_context(api_request), surface)

    handled, _ = dispatch_slash_command("/tokens", "", callbacks)

    assert handled is True
    assert calls == [("GET", "/ops/threads/thread-123/usage")]
    assert surface.usage_snapshots == [usage]


def test_shared_executor_reset_confirms_then_posts_backend_reset():
    calls: list[tuple[str, str]] = []

    def api_request(config, method, path, **kwargs):
        del config, kwargs
        calls.append((method, path))
        return 204, {}

    surface = _surface()
    callbacks = build_terminal_command_callbacks(_context(api_request), surface)

    handled, _ = dispatch_slash_command("/reset", "", callbacks)

    assert handled is True
    assert surface.confirmations == ["[bold yellow]Reset backend thread context? (y/N): [/bold yellow]"]
    assert calls == [("POST", "/ops/threads/thread-123/reset")]


def test_shared_executor_effort_and_permissions_use_thread_config_contract():
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def api_request(config, method, path, **kwargs):
        del config
        calls.append((method, path, kwargs["json_body"]))
        return 200, {}

    surface = _surface()
    callbacks = build_terminal_command_callbacks(_context(api_request), surface)

    handled_effort, _ = dispatch_slash_command("/effort", "high", callbacks)
    handled_permissions, _ = dispatch_slash_command("/permissions", "auto-edit", callbacks)

    assert handled_effort is True
    assert handled_permissions is True
    assert calls == [
        ("POST", "/ops/threads/thread-123/config", {"effort": "high"}),
        ("POST", "/ops/threads/thread-123/config", {"permissions": "auto-edit"}),
    ]


def test_shared_executor_workspace_mode_uses_thread_config_contract():
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def api_request(config, method, path, **kwargs):
        del config
        calls.append((method, path, kwargs["json_body"]))
        return 200, {}

    surface = _surface()
    callbacks = build_terminal_command_callbacks(_context(api_request), surface)

    handled, _ = dispatch_slash_command("/workspace-mode", "source_repo", callbacks)

    assert handled is True
    assert calls == [
        ("POST", "/ops/threads/thread-123/config", {"workspace_mode": "source_repo"}),
    ]


def test_shared_executor_workspace_mode_without_arg_reads_authoritative_status():
    calls: list[tuple[str, str]] = []
    snapshot = {"workspace_mode": "ephemeral", "orchestrator_authority": "gimo"}

    def api_request(config, method, path, **kwargs):
        del config, kwargs
        calls.append((method, path))
        return 200, snapshot

    surface = _surface()
    callbacks = build_terminal_command_callbacks(_context(api_request), surface)

    handled, _ = dispatch_slash_command("/mode", "", callbacks)

    assert handled is True
    assert calls == [("GET", "/ops/operator/status")]
    assert surface.rendered


def test_shared_executor_add_uses_thread_context_contract():
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def api_request(config, method, path, **kwargs):
        del config
        calls.append((method, path, kwargs["json_body"]))
        return 201, {}

    surface = _surface()
    callbacks = build_terminal_command_callbacks(_context(api_request), surface)

    handled, _ = dispatch_slash_command("/add", "README.md", callbacks)

    assert handled is True
    assert calls == [("POST", "/ops/threads/thread-123/context/add", {"path": "README.md"})]


def test_shared_executor_provider_switch_uses_canonical_backend_routes():
    calls: list[tuple[str, str, Any]] = []
    snapshot = {"active_provider": "openai", "active_model": "gpt-5"}

    def api_request(config, method, path, **kwargs):
        del config
        calls.append((method, path, kwargs.get("json_body")))
        if path == "/ops/provider/select":
            return 200, {"ok": True}
        if path == "/ops/operator/status":
            return 200, snapshot
        raise AssertionError(path)

    surface = _surface()
    callbacks = build_terminal_command_callbacks(_context(api_request), surface)

    handled, outcome = dispatch_slash_command("/provider", "openai gpt-5", callbacks)

    assert handled is True
    assert outcome is not None and outcome.updated_model == "gpt-5"
    assert calls == [
        ("POST", "/ops/provider/select", {"provider_id": "openai", "model": "gpt-5"}),
        ("GET", "/ops/operator/status", None),
    ]


def test_shared_executor_model_persists_local_preference():
    saved: list[dict[str, Any]] = []

    def api_request(config, method, path, **kwargs):
        raise AssertionError(f"Unexpected backend call: {method} {path} {kwargs}")

    surface = _surface()
    context = _context(api_request, config={"orchestrator": {}}, save_calls=saved)
    callbacks = build_terminal_command_callbacks(context, surface)

    handled, outcome = dispatch_slash_command("/model", "gpt-5.4", callbacks)

    assert handled is True
    assert outcome is not None and outcome.updated_model == "gpt-5.4"
    assert context.config["orchestrator"]["preferred_model"] == "gpt-5.4"
    assert saved


def test_shared_executor_merge_delegates_to_backend_even_if_not_awaiting():
    """CLI no longer pre-validates merge status; backend is authoritative."""
    calls: list[tuple[str, str]] = []
    snapshot = {"active_run_id": "run-1", "active_run_status": "EXECUTING"}

    def api_request(config, method, path, **kwargs):
        del config, kwargs
        calls.append((method, path))
        if path == "/ops/operator/status":
            return 200, snapshot
        if path == "/ops/runs/run-1/merge":
            return 400, {"detail": "Run is not in AWAITING_MERGE status"}
        raise AssertionError(path)

    surface = _surface()
    callbacks = build_terminal_command_callbacks(_context(api_request), surface)

    handled, _ = dispatch_slash_command("/merge", "", callbacks)

    assert handled is True
    assert calls == [
        ("GET", "/ops/operator/status"),
        ("POST", "/ops/runs/run-1/merge"),
    ]


def test_shared_executor_merge_infers_run_and_posts_canonical_merge():
    calls: list[tuple[str, str]] = []
    snapshot = {"active_run_id": "run-1", "active_run_status": "AWAITING_MERGE"}

    def api_request(config, method, path, **kwargs):
        del config, kwargs
        calls.append((method, path))
        if path == "/ops/operator/status":
            return 200, snapshot
        if path == "/ops/runs/run-1/merge":
            return 200, {"status": "done", "message": "merged"}
        raise AssertionError(path)

    surface = _surface()
    callbacks = build_terminal_command_callbacks(_context(api_request), surface)

    handled, _ = dispatch_slash_command("/merge", "", callbacks)

    assert handled is True
    assert calls == [
        ("GET", "/ops/operator/status"),
        ("POST", "/ops/runs/run-1/merge"),
    ]
