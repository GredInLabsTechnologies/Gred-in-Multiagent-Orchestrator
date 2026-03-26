from __future__ import annotations

from dataclasses import dataclass
from subprocess import CompletedProcess
from typing import Any, Callable, Protocol

from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from cli_commands import get_help_text


@dataclass
class TerminalCommandOutcome:
    updated_model: str | None = None
    should_exit: bool = False


@dataclass
class TerminalCommandContext:
    config: dict[str, Any]
    workspace_root: str
    thread_id: str | None
    api_request: Callable[..., tuple[int, Any]]
    save_config: Callable[[dict[str, Any]], None]
    git_command: Callable[[list[str]], CompletedProcess[str]]


class TerminalSurfaceAdapter(Protocol):
    def render(self, renderable: Any) -> None: ...

    def render_message(self, message: str) -> None: ...

    def clear_view(self) -> None: ...

    def confirm(
        self,
        prompt: str,
        on_confirm: Callable[[], Any],
        *,
        cancel_message: str,
    ) -> Any: ...

    def get_debug(self) -> bool: ...

    def set_debug(self, value: bool) -> None: ...

    def render_status_snapshot(self, snapshot: dict[str, Any]) -> None: ...

    def render_usage_snapshot(self, usage: dict[str, Any]) -> None: ...


def fetch_operator_status_snapshot(
    config: dict[str, Any],
    api_request: Callable[..., tuple[int, Any]],
) -> tuple[int, Any]:
    return api_request(config, "GET", "/ops/operator/status")


def _payload_detail(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if detail:
            return str(detail)
        message = payload.get("message")
        if message:
            return str(message)
    if isinstance(payload, str):
        return payload
    return str(payload)


def _render_backend_error(
    surface: TerminalSurfaceAdapter,
    prefix: str,
    status_code: int,
    payload: Any,
) -> None:
    surface.render_message(f"[red]{prefix} ({status_code}): {_payload_detail(payload)}[/red]")


def _require_status_snapshot(
    context: TerminalCommandContext,
    surface: TerminalSurfaceAdapter,
    *,
    error_prefix: str,
) -> dict[str, Any] | None:
    status_code, payload = fetch_operator_status_snapshot(context.config, context.api_request)
    if status_code != 200 or not isinstance(payload, dict):
        _render_backend_error(surface, error_prefix, status_code, payload)
        return None
    return payload


def _provider_table(payload: dict[str, Any]) -> Table:
    providers = payload.get("providers", {})
    table = Table(title="Configured Providers", show_header=True)
    table.add_column("Provider ID", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Role Configured", style="green")
    for provider_id, provider_data in providers.items():
        if not isinstance(provider_data, dict):
            table.add_row(str(provider_id), "unknown", "No")
            continue
        provider_type = provider_data.get("provider_type") or provider_data.get("type") or "unknown"
        role_configured = "Yes" if provider_data.get("role_bindings") else "No"
        table.add_row(str(provider_id), str(provider_type), role_configured)
    return table


def _workers_tree(payload: dict[str, Any]) -> Tree:
    providers = payload.get("providers", {})
    tree = Tree("Worker Pool & Role Assignments")
    roles_map: dict[str, list[str]] = {}
    unassigned: list[str] = []

    for provider_id, provider_data in providers.items():
        if not isinstance(provider_data, dict):
            unassigned.append(str(provider_id))
            continue
        bindings = provider_data.get("role_bindings", [])
        if not bindings:
            unassigned.append(str(provider_id))
        for role in bindings:
            roles_map.setdefault(str(role), []).append(str(provider_id))

    for role, provider_ids in sorted(roles_map.items()):
        role_node = tree.add(f"[magenta]{role.capitalize()}[/magenta]")
        for provider_id in provider_ids:
            provider_data = providers.get(provider_id, {})
            provider_type = provider_data.get("provider_type") or provider_data.get("type") or "unknown"
            models = provider_data.get("models", [])
            role_node.add(
                f"[green]{provider_id}[/green] [dim]({provider_type})[/dim] - {len(models)} models"
            )

    if unassigned:
        unassigned_node = tree.add("[yellow]Unassigned[/yellow]")
        for provider_id in sorted(unassigned):
            provider_data = providers.get(provider_id, {})
            provider_type = provider_data.get("provider_type") or provider_data.get("type") or "unknown"
            unassigned_node.add(f"{provider_id} [dim]({provider_type})[/dim]")

    return tree


def _show_help(surface: TerminalSurfaceAdapter) -> None:
    surface.render(Panel(get_help_text(), title="Chat Commands", border_style="cyan"))


def build_terminal_command_callbacks(
    context: TerminalCommandContext,
    surface: TerminalSurfaceAdapter,
) -> dict[str, Callable[..., Any]]:
    def show_help() -> None:
        _show_help(surface)

    def show_workspace() -> None:
        surface.render(Panel(context.workspace_root, title="Workspace", border_style="blue"))

    def show_thread() -> None:
        surface.render(Panel(str(context.thread_id or "unknown"), title="Thread", border_style="blue"))

    def exit_session() -> TerminalCommandOutcome:
        return TerminalCommandOutcome(should_exit=True)

    def handle_provider(arg: str) -> TerminalCommandOutcome | None:
        normalized = arg.strip()
        if normalized == "list":
            status_code, payload = context.api_request(context.config, "GET", "/ops/provider")
            if status_code != 200 or not isinstance(payload, dict):
                _render_backend_error(surface, "Failed to fetch providers", status_code, payload)
                return None
            surface.render(_provider_table(payload))
            return None

        if normalized.startswith("switch "):
            normalized = normalized[len("switch ") :].strip()

        if not normalized:
            snapshot = _require_status_snapshot(
                context,
                surface,
                error_prefix="Failed to fetch authoritative provider status",
            )
            if snapshot is None:
                return None
            provider_id = str(snapshot.get("active_provider") or "unknown")
            model_id = str(snapshot.get("active_model") or "unknown")
            surface.render(
                Panel(
                    "\n".join(
                        [
                            f"Provider: [bold]{provider_id}[/bold]",
                            f"Model: [bold]{model_id}[/bold]",
                            "",
                            "Use /provider list or /provider <id> [model].",
                        ]
                    ),
                    title="Provider Selection",
                    border_style="yellow",
                )
            )
            return None

        parts = normalized.split()
        provider_id = parts[0]
        model_id = parts[1] if len(parts) > 1 else None
        prefer_family = "qwen" if "ollama" in provider_id.lower() and model_id is None else None

        payload: dict[str, Any] = {"provider_id": provider_id}
        if model_id:
            payload["model"] = model_id
        if prefer_family:
            payload["prefer_family"] = prefer_family

        status_code, response_payload = context.api_request(
            context.config,
            "POST",
            "/ops/provider/select",
            json_body=payload,
        )
        if status_code != 200:
            _render_backend_error(surface, "Failed to switch provider", status_code, response_payload)
            return None

        snapshot = _require_status_snapshot(
            context,
            surface,
            error_prefix="Failed to fetch provider status after switch",
        )
        if snapshot is None:
            return None

        active_provider = str(snapshot.get("active_provider") or "unknown")
        active_model = str(snapshot.get("active_model") or "unknown")
        surface.render(
            Panel(
                f"Provider: [bold]{active_provider}[/bold]\nModel: [bold]{active_model}[/bold]",
                title="Provider Switched",
                border_style="green",
            )
        )
        return TerminalCommandOutcome(updated_model=active_model)

    def handle_model(arg: str) -> TerminalCommandOutcome | None:
        normalized = arg.strip()
        if not normalized:
            snapshot = _require_status_snapshot(
                context,
                surface,
                error_prefix="Failed to fetch authoritative provider status",
            )
            if snapshot is None:
                return None
            preferred_model = str(context.config.get("orchestrator", {}).get("preferred_model") or "not set")
            active_model = str(snapshot.get("active_model") or "unknown")
            surface.render(
                Panel(
                    f"Preferred model: [bold]{preferred_model}[/bold]\nActive backend model: [bold]{active_model}[/bold]",
                    title="Model Selection",
                    border_style="yellow",
                )
            )
            return None

        context.config.setdefault("orchestrator", {})["preferred_model"] = normalized
        context.save_config(context.config)
        surface.render_message(f"[green]Preferred model set to '{normalized}'.[/green]")
        return TerminalCommandOutcome(updated_model=normalized)

    def list_models() -> None:
        status_code, payload = context.api_request(context.config, "GET", "/ops/provider/models")
        if status_code != 200:
            _render_backend_error(surface, "Failed to fetch models", status_code, payload)
            return None
        if not isinstance(payload, list):
            surface.render_message(f"[red]Unexpected models payload: {_payload_detail(payload)}[/red]")
            return None
        table = Table(title="Available Models", show_header=True)
        table.add_column("Model", style="cyan")
        for item in payload:
            model_name = item.get("id", str(item)) if isinstance(item, dict) else str(item)
            table.add_row(model_name)
        surface.render(table)
        return None

    def show_workers() -> None:
        status_code, payload = context.api_request(context.config, "GET", "/ops/provider")
        if status_code != 200 or not isinstance(payload, dict):
            _render_backend_error(surface, "Failed to fetch worker pool", status_code, payload)
            return None
        surface.render(Panel(_workers_tree(payload), border_style="blue", title="Agents Topology"))
        return None

    def show_status() -> None:
        snapshot = _require_status_snapshot(
            context,
            surface,
            error_prefix="Failed to fetch authoritative status",
        )
        if snapshot is None:
            return None
        surface.render_status_snapshot(snapshot)
        return None

    def undo() -> None:
        result = context.git_command(["revert", "--no-edit", "HEAD"])
        if result.returncode == 0:
            surface.render(
                Panel(
                    result.stdout.strip() or "Revert successful.",
                    title="/undo",
                    border_style="green",
                )
            )
            return None
        surface.render(
            Panel(
                result.stderr.strip() or result.stdout.strip() or "Revert failed.",
                title="/undo failed",
                border_style="red",
            )
        )
        return None

    def clear_view() -> None:
        surface.clear_view()
        surface.render_message("[dim]Chat cleared (thread and context intact).[/dim]")
        return None

    def reset_context() -> Any:
        if not context.thread_id:
            surface.render_message("[red]Reset requires an active thread.[/red]")
            return None

        def _do_reset() -> None:
            status_code, payload = context.api_request(
                context.config,
                "POST",
                f"/ops/threads/{context.thread_id}/reset",
            )
            if status_code in {200, 204}:
                surface.render_message("[green]Thread context reset.[/green]")
                return None
            _render_backend_error(surface, "Reset failed", status_code, payload)
            return None

        return surface.confirm(
            "[bold yellow]Reset backend thread context? (y/N): [/bold yellow]",
            _do_reset,
            cancel_message="[dim]Reset cancelled.[/dim]",
        )

    def show_tokens() -> None:
        if not context.thread_id:
            surface.render_message("[red]Token usage requires an active thread.[/red]")
            return None
        status_code, payload = context.api_request(
            context.config,
            "GET",
            f"/ops/threads/{context.thread_id}/usage",
        )
        if status_code != 200 or not isinstance(payload, dict):
            _render_backend_error(surface, "Failed to fetch thread usage", status_code, payload)
            return None
        surface.render_usage_snapshot(payload)
        return None

    def show_diff() -> None:
        status_code, payload = context.api_request(context.config, "GET", "/ops/files/diff")
        if status_code != 200:
            _render_backend_error(surface, "Diff unavailable", status_code, payload)
            return None
        if isinstance(payload, dict):
            diff_text = payload.get("diff") or payload.get("content") or str(payload)
        else:
            diff_text = str(payload)
        if not diff_text.strip():
            surface.render_message("[dim]No active diff.[/dim]")
            return None
        surface.render(Panel(diff_text, title="/diff", border_style="yellow"))
        return None

    def set_effort(effort_val: str) -> None:
        if not context.thread_id:
            surface.render_message("[red]Effort requires an active thread.[/red]")
            return None
        status_code, payload = context.api_request(
            context.config,
            "POST",
            f"/ops/threads/{context.thread_id}/config",
            json_body={"effort": effort_val},
        )
        if status_code in {200, 204}:
            surface.render_message(f"[green]Orchestrator effort set to [bold]{effort_val}[/bold].[/green]")
            return None
        _render_backend_error(surface, "Set effort failed", status_code, payload)
        return None

    def set_permissions(permission_val: str) -> None:
        if not context.thread_id:
            surface.render_message("[red]Permissions require an active thread.[/red]")
            return None
        status_code, payload = context.api_request(
            context.config,
            "POST",
            f"/ops/threads/{context.thread_id}/config",
            json_body={"permissions": permission_val},
        )
        if status_code in {200, 204}:
            surface.render_message(f"[green]Permissions set to [bold]perm:{permission_val}[/bold].[/green]")
            return None
        _render_backend_error(surface, "Set permissions failed", status_code, payload)
        return None

    def add_file(path_val: str) -> None:
        if not context.thread_id:
            surface.render_message("[red]Adding context requires an active thread.[/red]")
            return None
        status_code, payload = context.api_request(
            context.config,
            "POST",
            f"/ops/threads/{context.thread_id}/context/add",
            json_body={"path": path_val},
        )
        if status_code in {200, 201}:
            surface.render_message(f"[green]Added to context: [bold]{path_val}[/bold][/green]")
            return None
        _render_backend_error(surface, "Add file failed", status_code, payload)
        return None

    def invalid_arg(message: str) -> None:
        surface.render_message(f"[yellow]{message}[/yellow]")
        return None

    def toggle_debug() -> None:
        next_state = not surface.get_debug()
        surface.set_debug(next_state)
        surface.render_message(f"[dim]Debug mode {'enabled' if next_state else 'disabled'}[/dim]")
        return None

    def merge_run(arg: str) -> None:
        run_id = arg.strip()
        if not run_id:
            snapshot = _require_status_snapshot(
                context,
                surface,
                error_prefix="Failed to fetch status to infer merge target",
            )
            if snapshot is None:
                return None
            run_id = str(snapshot.get("active_run_id") or "")
            if not run_id:
                surface.render_message("[yellow]No active run found to merge.[/yellow]")
                return None
            if snapshot.get("active_run_status") != "AWAITING_MERGE":
                surface.render_message(
                    f"[yellow]Active run {run_id} is in status '{snapshot.get('active_run_status')}', not AWAITING_MERGE.[/yellow]"
                )
                return None

        status_code, payload = context.api_request(
            context.config,
            "POST",
            f"/ops/runs/{run_id}/merge",
        )
        if status_code != 200 or not isinstance(payload, dict):
            _render_backend_error(surface, "Merge failed", status_code, payload)
            return None
        surface.render(
            Panel(
                "\n".join(
                    [
                        f"Run ID: [bold]{run_id}[/bold]",
                        f"Status: {payload.get('status', 'unknown')}",
                        f"Message: {payload.get('message', 'n/a')}",
                    ]
                ),
                title="/merge successful",
                border_style="green",
            )
        )
        return None

    def unknown_command(command_name: str) -> None:
        surface.render_message(f"[yellow]Unknown command: {command_name}. Use /help.[/yellow]")
        return None

    return {
        "show_help": show_help,
        "show_workspace": show_workspace,
        "show_thread": show_thread,
        "exit_session": exit_session,
        "handle_provider": handle_provider,
        "handle_model": handle_model,
        "list_models": list_models,
        "show_workers": show_workers,
        "show_status": show_status,
        "undo": undo,
        "clear_view": clear_view,
        "reset_context": reset_context,
        "show_tokens": show_tokens,
        "show_diff": show_diff,
        "set_effort": set_effort,
        "set_permissions": set_permissions,
        "add_file": add_file,
        "toggle_debug": toggle_debug,
        "merge_run": merge_run,
        "invalid_arg": invalid_arg,
        "unknown_command": unknown_command,
    }
