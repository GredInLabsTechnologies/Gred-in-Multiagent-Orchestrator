"""Interactive agentic chat session and slash command handling."""

from __future__ import annotations

import json
from typing import Any

import httpx
import typer
from rich.panel import Panel
from rich.table import Table

from gimo_cli import console
from gimo_cli.api import (
    api_request,
    api_settings,
    chat_provider_summary,
    provider_config_request,
    resolve_token,
)
from gimo_cli.config import (
    get_budget_color,
    parse_yes_no,
    project_root,
    ensure_project_dirs,
    history_dir,
    save_config,
)
from gimo_cli.stream import git_command
from cli_commands import dispatch_slash_command
from terminal_command_executor import (
    TerminalCommandContext,
    TerminalCommandOutcome,
    TerminalSurfaceAdapter,
    build_terminal_command_callbacks,
)


class ConsoleTerminalSurface(TerminalSurfaceAdapter):
    def __init__(self, *, renderer: Any = None, workspace_root: str) -> None:
        self._renderer = renderer
        self._workspace_root = workspace_root

    def render(self, renderable: Any) -> None:
        console.print(renderable)

    def render_message(self, message: str) -> None:
        console.print(message)

    def clear_view(self) -> None:
        console.clear()

    def confirm(self, prompt: str, on_confirm, *, cancel_message: str) -> Any:
        try:
            answer = console.input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            console.print(cancel_message)
            return None
        if not parse_yes_no(answer):
            console.print(cancel_message)
            return None
        return on_confirm()

    def get_debug(self) -> bool:
        return bool(self._renderer.verbose) if self._renderer is not None else False

    def set_debug(self, value: bool) -> None:
        if self._renderer is not None:
            self._renderer.verbose = value

    def render_status_snapshot(self, snapshot: dict[str, Any]) -> None:
        version = str(snapshot.get("backend_version") or "?")
        provider = str(snapshot.get("active_provider") or "unknown")
        model = str(snapshot.get("active_model") or "unknown")
        permissions = str(snapshot.get("permissions") or "suggest")
        _hitl_desc = {
            "suggest": "agent proposes, you approve",
            "auto-edit": "auto-applies file edits",
            "full-auto": "fully autonomous execution",
        }
        permissions_hint = _hitl_desc.get(permissions, "")
        workspace_mode = str(snapshot.get("workspace_mode") or "ephemeral")
        orchestrator_authority = str(snapshot.get("orchestrator_authority") or "gimo")
        branch = str(snapshot.get("branch") or "?")
        budget_status = str(snapshot.get("budget_status") or "unknown")
        budget_pct = snapshot.get("budget_percentage")
        context_status = str(snapshot.get("context_status") or "0%")
        active_run_id = snapshot.get("active_run_id")
        active_run_status = snapshot.get("active_run_status")
        last_thread = str(snapshot.get("last_thread") or "n/a")
        last_turn = str(snapshot.get("last_turn") or "n/a")
        alerts = snapshot.get("alerts")
        if not isinstance(alerts, list):
            alerts = []

        lines = [
            f"System: [bold]v{version}[/bold]",
            f"Provider: [cyan]{provider}[/cyan] / {model}",
            f"Permissions: [bold]{permissions}[/bold] [dim]({permissions_hint})[/dim]" if permissions_hint else f"Permissions: [bold]{permissions}[/bold]",
            f"Workspace mode: [bold]{workspace_mode}[/bold]",
            f"Orchestrator authority: [bold]{orchestrator_authority}[/bold]",
            f"Workspace: [dim]{self._workspace_root}[/dim]",
            f"Branch: [cyan]{branch}[/cyan]",
            f"Budget: [bold]{budget_status}[/bold]"
            + (f" ({budget_pct:.1f}% remaining)" if isinstance(budget_pct, (int, float)) else ""),
            f"Context: [bold]{context_status}[/bold]",
            f"Active run: [bold]{active_run_id or 'none'}[/bold]"
            + (f" ({active_run_status})" if active_run_status else ""),
            f"Last thread: {last_thread} turn {last_turn}",
        ]
        if alerts:
            lines.append("Alerts:")
            for alert in alerts:
                if isinstance(alert, dict):
                    level = str(alert.get("level") or "info")
                    message = str(alert.get("message") or "")
                else:
                    level = "warning"
                    message = str(alert)
                color = "red" if level == "error" else "yellow" if level == "warning" else "blue"
                lines.append(f" - [{color}]{message}[/{color}]")
        console.print(Panel("\n".join(lines), title="Authoritative Status", border_style="magenta"))

    def render_usage_snapshot(self, usage: dict[str, Any]) -> None:
        if not usage:
            console.print("[dim]No token usage data available for this thread.[/dim]")
            return
        lines = [
            f"Input tokens:  [cyan]{usage.get('input_tokens', 0):,}[/cyan]",
            f"Output tokens: [cyan]{usage.get('output_tokens', 0):,}[/cyan]",
            f"Total tokens:  [bold]{usage.get('total_tokens', 0):,}[/bold]",
            f"Cost:          [green]${usage.get('cost_usd', 0.0):.5f}[/green]",
        ]
        context_pct = usage.get("context_window_pct")
        if isinstance(context_pct, (int, float)):
            lines.append(f"Context:       [bold]{context_pct:.1f}%[/bold]")
        console.print(Panel("\n".join(lines), title="Token Usage", border_style="cyan"))


def get_telemetry_toolbar(config: dict[str, Any]) -> str:
    status, payload = api_request(config, "GET", "/ops/operator/status")
    if status == 200 and isinstance(payload, dict):
        rem_pct = payload.get("budget_percentage", 100.0)
        ctx_status = payload.get("context_status", "0%")

        alerts = []
        for n in payload.get("alerts", []):
            lvl = n.get("level", "info")
            msg = n.get("message", "")
            if lvl == "warning":
                alerts.append(f"<ansiyellow>[!]\ufe0f {msg}</ansiyellow>")
            elif lvl == "error":
                alerts.append(f"<ansired>[X] {msg}</ansired>")

        alerts_line = " | ".join(alerts) if alerts else "<ansigray>No active alerts</ansigray>"

        color = get_budget_color(rem_pct)
        if color == "red": color = "ansired"
        elif color == "yellow": color = "ansiyellow"
        else: color = "ansigreen"

        telemetry_line = f" [$] Budget: <{color}>{100-rem_pct:.1f}% used</{color}> | [Brain] Context: <b>{ctx_status}</b> "
        return f"{telemetry_line}\n \U0001f514 ALERTS: {alerts_line} "

    return " [$] Telemetry unavailable \n \U0001f514 ALERTS: <ansigray>None</ansigray> "


def render_chat_models(config: dict[str, Any]) -> None:
    status_code, payload = api_request(config, "GET", "/ops/provider/models")
    if status_code != 200:
        console.print(f"[red]Failed to fetch models ({status_code}): {payload}[/red]")
        return
    if not isinstance(payload, list):
        console.print(payload)
        return
    table = Table(title="Available Models", show_header=True)
    table.add_column("Model", style="cyan")
    for item in payload:
        model_name = item.get("id", str(item)) if isinstance(item, dict) else str(item)
        table.add_row(model_name)
    console.print(table)


def _build_terminal_command_context(
    config: dict[str, Any],
    *,
    workspace_root: str,
    thread_id: str | None,
) -> TerminalCommandContext:
    return TerminalCommandContext(
        config=config,
        workspace_root=workspace_root,
        thread_id=thread_id,
        api_request=api_request,
        save_config=save_config,
        git_command=git_command,
    )


def handle_chat_slash_command(
    config: dict[str, Any],
    user_input: str,
    *,
    workspace_root: str,
    thread_id: str,
    renderer: Any = None,
) -> tuple[bool, TerminalCommandOutcome | None]:
    if not user_input.startswith("/"):
        return False, None

    parts = user_input.strip().split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    surface = ConsoleTerminalSurface(renderer=renderer, workspace_root=workspace_root)
    context = _build_terminal_command_context(
        config,
        workspace_root=workspace_root,
        thread_id=thread_id,
    )
    callbacks = build_terminal_command_callbacks(context, surface)
    handled, outcome = dispatch_slash_command(command, argument, callbacks)
    return handled, outcome if isinstance(outcome, TerminalCommandOutcome) else None


def preflight_check(config: dict[str, Any]) -> tuple[bool, str]:
    try:
        status_code, _ = api_request(config, "GET", "/health")
        if status_code != 200:
            return False, f"Server returned HTTP {status_code}. Is GIMO running?"
    except Exception as exc:
        return False, f"Cannot reach GIMO server: {exc}\nStart it with: gimo.cmd"

    try:
        status_code, payload = provider_config_request(config)
        if status_code != 200:
            return False, "Cannot fetch provider config."
        if isinstance(payload, dict):
            orch_provider = payload.get("orchestrator_provider") or payload.get("active")
            if not orch_provider:
                return False, "No orchestrator provider configured.\nConfigure one in the UI: Settings > Providers"
    except Exception as exc:
        return False, f"Provider check failed: {exc}"

    return True, ""


def interactive_chat(config: dict[str, Any]) -> None:
    """Run the interactive agentic chat session."""
    from gimo_cli_renderer import ChatRenderer

    renderer = ChatRenderer(console, verbose=config.get("orchestrator", {}).get("verbose", False))
    workspace_root = str(project_root())

    ok, err = preflight_check(config)
    if not ok:
        renderer.render_preflight_error(err, hint="Run 'gimo status' for diagnostics.")
        raise typer.Exit(1)

    provider_id, model = chat_provider_summary(config)

    with console.status("[dim]Creating session...[/dim]"):
        status_code, thread_payload = api_request(
            config,
            "POST",
            "/ops/threads",
            params={"workspace_root": workspace_root, "title": "CLI Agentic Session"},
        )
    if status_code != 201 or not isinstance(thread_payload, dict):
        renderer.render_error(f"Failed to create thread ({status_code}): {thread_payload}")
        raise typer.Exit(1)

    thread_id = str(thread_payload.get("id") or "")
    if not thread_id:
        renderer.render_error("No thread id returned.")
        raise typer.Exit(1)

    renderer.render_session_header(
        provider_id=provider_id,
        model=model,
        workspace=workspace_root,
        thread_id=thread_id,
    )

    history_path = history_dir() / f"{thread_id}.log"
    ensure_project_dirs()

    while True:
        turn_interrupted = False
        try:
            renderer.telemetry_html = get_telemetry_toolbar(config)
            user_input = renderer.get_user_input()
        except KeyboardInterrupt:
            renderer.render_interrupted()
            continue
        if not user_input:
            continue
        handled, outcome = handle_chat_slash_command(
            config,
            user_input,
            workspace_root=workspace_root,
            thread_id=thread_id,
            renderer=renderer,
        )
        if handled:
            if outcome is not None and outcome.updated_model is not None:
                model = outcome.updated_model
            if outcome is not None and outcome.should_exit:
                console.print("[dim]Session ended.[/dim]")
                break
            continue

        with history_path.open("a", encoding="utf-8") as f:
            f.write(f"> {user_input}\n")

        base_url, timeout_seconds = api_settings(config)
        auth_token = resolve_token("operator", config)
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        headers["Accept"] = "text/event-stream"
        headers["X-GIMO-Surface"] = "cli"

        chat_response = ""
        usage = {}

        try:
            stream_timeout = httpx.Timeout(
                connect=timeout_seconds,
                read=600.0,
                write=timeout_seconds,
                pool=timeout_seconds,
            )
            with httpx.Client(timeout=stream_timeout) as client:
                with renderer.render_thinking():
                    with client.stream(
                        "POST",
                        f"{base_url}/ops/threads/{thread_id}/chat/stream",
                        json={"content": user_input},
                        headers=headers,
                    ) as response:
                        if response.status_code != 200:
                            raise httpx.HTTPStatusError(
                                f"Stream returned {response.status_code}",
                                request=response.request,
                                response=response,
                            )

                        current_event_type = "message"
                        renderer._generation_active = True
                        try:
                            for line in response.iter_lines():
                                if not line or line.startswith(":"):
                                    continue

                                if line.startswith("event: "):
                                    current_event_type = line[7:].strip()
                                    continue
                                if not line.startswith("data: "):
                                    continue

                                raw_data = line[6:].strip()
                                if not raw_data:
                                    continue

                                try:
                                    data = json.loads(raw_data)
                                except json.JSONDecodeError:
                                    continue

                                evt = current_event_type
                                renderer.render_sse_raw(evt, raw_data)

                                if evt == "text_delta":
                                    chat_response += data.get("content", "")
                                elif evt == "tool_call_start":
                                    renderer.render_tool_call_start(
                                        data.get("tool_name", "?"),
                                        data.get("arguments", {}),
                                        data.get("risk", "LOW"),
                                    )
                                elif evt == "tool_approval_required":
                                    approved = renderer.render_hitl_prompt(
                                        data.get("tool_name", "?"),
                                        data.get("arguments", {}),
                                    )
                                    try:
                                        client.post(
                                            f"{base_url}/ops/threads/{thread_id}/approve-tool",
                                            params={
                                                "tool_call_id": data.get("tool_call_id", ""),
                                                "approved": str(approved).lower(),
                                            },
                                            headers={"Authorization": f"Bearer {auth_token}"} if auth_token else {},
                                        )
                                    except Exception:
                                        pass
                                elif evt == "tool_call_end":
                                    renderer.render_tool_call_result(
                                        data.get("tool_name", "?"),
                                        data.get("status", "error"),
                                        data.get("duration", 0.0),
                                        data.get("risk", "LOW"),
                                    )
                                elif evt == "done":
                                    chat_response = data.get("response", chat_response)
                                    usage = data.get("usage", {})
                                elif evt == "error":
                                    renderer.render_error(data.get("message", "Unknown error"))
                                elif evt == "user_question":
                                    question = data.get("question", "")
                                    options = data.get("options", [])
                                    context = data.get("context", "")
                                    renderer.render_user_question(question, options, context)
                                elif evt == "plan_proposed":
                                    plan_data = data
                                    renderer.render_plan(plan_data)
                                    approval = renderer.get_plan_approval()
                                    try:
                                        client.post(
                                            f"{base_url}/ops/threads/{thread_id}/plan/respond",
                                            params={"action": approval},
                                            json={"feedback": "User feedback from CLI"},
                                            headers={"Authorization": f"Bearer {auth_token}"} if auth_token else {},
                                        )
                                        if approval == "approve":
                                            renderer.console.print("[green]\u2713 Plan approved. Execution started.[/green]")
                                        elif approval == "reject":
                                            renderer.console.print("[red]\u2717 Plan rejected. Agent will revise.[/red]")
                                        else:
                                            renderer.console.print("[yellow]Plan modification not yet implemented in CLI. Please approve or reject.[/yellow]")
                                    except Exception as e:
                                        renderer.render_error(f"Failed to submit plan response: {e}")
                                elif evt == "confirmation_required":
                                    tool_name = data.get("tool_name", "?")
                                    message = data.get("message", "")
                                    renderer.console.print()
                                    renderer.console.print(Panel(
                                        f"{message}\n\nTool: [bold]{tool_name}[/bold]",
                                        title="\u26a0 Confirmation Required",
                                        border_style="yellow",
                                    ))
                                    try:
                                        answer = renderer.console.input("[bold yellow]Approve? (y/N): [/bold yellow]").strip()
                                        approved = parse_yes_no(answer)
                                        try:
                                            client.post(
                                                f"{base_url}/ops/threads/{thread_id}/approve-tool",
                                                params={
                                                    "tool_call_id": data.get("tool_call_id", ""),
                                                    "approved": str(approved).lower(),
                                                },
                                                headers={"Authorization": f"Bearer {auth_token}"} if auth_token else {},
                                            )
                                        except Exception:
                                            pass
                                        if not approved:
                                            renderer.console.print("[dim]Confirmation denied. Agent will skip this action.[/dim]")
                                    except (EOFError, KeyboardInterrupt):
                                        pass
                                elif evt == "session_start":
                                    mood = data.get("mood", "neutral")
                                    renderer.render_mood_indicator(mood)

                        except KeyboardInterrupt:
                            turn_interrupted = True
                            renderer.render_interrupted()
                            break
                        finally:
                            renderer._generation_active = False

        except (httpx.HTTPStatusError, httpx.ConnectError):
            try:
                with httpx.Client(timeout=max(timeout_seconds, 300.0)) as client:
                    with renderer.render_thinking():
                        fallback_headers = {"X-GIMO-Surface": "cli"}
                        if auth_token:
                            fallback_headers["Authorization"] = f"Bearer {auth_token}"
                        response = client.post(
                            f"{base_url}/ops/threads/{thread_id}/chat",
                            json={"content": user_input},
                            headers=fallback_headers,
                        )

                if response.status_code != 200:
                    renderer.render_error(f"HTTP {response.status_code}: {response.text[:200]}")
                    continue

                payload = response.json()
                tool_calls = payload.get("tool_calls", [])
                if tool_calls:
                    renderer.render_tool_calls(tool_calls)
                chat_response = payload.get("response", "")
                usage = payload.get("usage", {})

            except KeyboardInterrupt:
                turn_interrupted = True
                renderer.render_interrupted()
            except httpx.TimeoutException:
                renderer.render_error("Request timed out. The LLM may need more time.")
                continue
            except Exception as exc:
                renderer.render_error(f"Request failed: {exc}")
                continue
        except httpx.TimeoutException:
            renderer.render_error("Stream timed out. The LLM may need more time.")
            continue
        except Exception as exc:
            renderer.render_error(f"Stream failed: {exc}")
            continue

        if turn_interrupted:
            continue

        renderer.render_response(chat_response)
        renderer.render_footer(usage)

        with history_path.open("a", encoding="utf-8") as f:
            f.write(f"{chat_response}\n---\n")
