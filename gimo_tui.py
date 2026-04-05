import json
import httpx
import subprocess
from typing import Any, Callable, Dict, Optional

import cli_commands
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Input, RichLog
from rich.text import Text
from rich.panel import Panel

from cli_policies import get_budget_color

# Use canonical gimo_cli modules directly (not legacy gimo.py shim)
from gimo_cli.api import api_request as _api_request, api_settings as _api_settings, resolve_token
from gimo_cli.config import save_config as _save_config
from terminal_command_executor import (
    TerminalCommandContext,
    TerminalCommandOutcome,
    TerminalSurfaceAdapter,
    build_terminal_command_callbacks,
    fetch_operator_status_snapshot,
)

# Constants to avoid literal duplication
CHAT_LOG_ID = "#chat-log"
NOTICES_CONTENT_ID = "#notices-content"
GRAPH_CONTENT_ID = "#graph-content"
ECO_CONTENT_ID = "#eco-content"
NO_NOTICES_MSG = "   No active notices."


class TextualTerminalSurface(TerminalSurfaceAdapter):
    def __init__(self, app: "GimoApp") -> None:
        self._app = app

    def render(self, renderable: Any) -> None:
        self._app._safe_call(self._app._write_log, renderable)

    def render_message(self, message: str) -> None:
        self._app._safe_call(self._app._write_log, message)

    def clear_view(self) -> None:
        self._app._safe_call(self._app.action_clear_log)

    def confirm(
        self,
        prompt: str,
        on_confirm: Callable[[], Any],
        *,
        cancel_message: str,
    ) -> Any:
        self._app._safe_call(self._app._queue_command_confirmation, prompt, on_confirm, cancel_message)
        return None

    def get_debug(self) -> bool:
        return bool(self._app.verbose)

    def set_debug(self, value: bool) -> None:
        self._app.verbose = value

    def render_status_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._app._safe_call(self._app._apply_status_snapshot, snapshot)
        provider = snapshot.get("active_provider", "?")
        model = snapshot.get("active_model", "?")
        workspace_mode = snapshot.get("workspace_mode", "ephemeral")
        orchestrator_authority = snapshot.get("orchestrator_authority", "gimo")
        self._app._safe_call(
            self._app._write_log,
            Panel(
                f"Provider: [cyan]{provider}[/cyan]\nModel: [dim]{model}[/dim]\nWorkspace mode: [bold]{workspace_mode}[/bold]\nOrchestrator: [bold]{orchestrator_authority}[/bold]",
                title="Authoritative Status",
                border_style="green",
            ),
        )

    def render_usage_snapshot(self, usage: dict[str, Any]) -> None:
        if not usage:
            self._app._safe_call(self._app._write_log, "[dim]No token usage data available for this thread.[/dim]")
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
        self._app._safe_call(
            self._app._write_log,
            Panel("\n".join(lines), title="Token Usage", border_style="cyan"),
        )

class GimoHeader(Static):
    """Fixed header: repo | branch | model | perm | budget | ctx"""
    def compose(self) -> ComposeResult:
        yield Static("REPO: - | BRANCH: - | MODEL: - | PERM: - | BUDGET: - | CTX: -", id="header-text")

class GraphWidget(Static):
    """Renders the agentic swarm topology."""
    def compose(self) -> ComposeResult:
        yield Static("   Loading topology...", classes="content-area", id=GRAPH_CONTENT_ID[1:])

class EconomyWidget(Static):
    """Renders the token usage and limits."""
    def compose(self) -> ComposeResult:
        yield Static("   Fetching telemetry...", classes="content-area", id=ECO_CONTENT_ID[1:])

class NoticesWidget(Static):
    """Renders temporary system notices from canonical policy."""
    def compose(self) -> ComposeResult:
        yield Static(NO_NOTICES_MSG, classes="content-area", id=NOTICES_CONTENT_ID[1:])

class ChatLogWidget(RichLog):
    """Renders the chat history cleanly."""
    pass

CHAT_LOG_ID = "#chat-log"

class GimoApp(App):
    """GIMO Orchestrator Textual App (Production Ready)."""
    
    TITLE = "GIMO Orchestrator"
    
    BINDINGS = [
        Binding("ctrl+c", "interrupt_or_quit", "Interrupt/Quit", show=True),
        Binding("ctrl+l", "clear_log", "Clear Chat", show=True),
        Binding("escape", "dismiss_notice", "Dismiss Notice", show=False),
        Binding("f5", "refresh_all", "Refresh Status", show=True),
    ]
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    GimoHeader {
        dock: top;
        height: 1;
        background: $primary;
        color: $text;
        text-align: center;
        content-align: center middle;
        text-style: bold;
    }

    #top-zone {
        height: 12;
        margin-bottom: 1;
    }
    
    GraphWidget {
        width: 60%;
        border: heavy $background;
        background: $boost;
        border-title-color: $accent;
    }
    
    #sidebar {
        width: 40%;
    }

    EconomyWidget, NoticesWidget {
        height: 50%;
        border: heavy $background;
        background: $boost;
        margin-left: 1;
    }
    
    EconomyWidget {
        border-title-color: $success;
    }

    NoticesWidget {
        border-title-color: $warning;
    }

    .content-area {
        padding: 1 2;
    }
    
    #middle-zone {
        height: 1fr;
        border: heavy $secondary;
        background: $boost;
    }
    
    ChatLogWidget {
        height: 1fr;
        padding: 0 1;
        scrollbar-gutter: stable;
    }
    
    #chat-input-box {
        dock: bottom;
        height: auto;
        border-top: solid $primary;
        background: $surface;
    }
    
    #chat-input {
        border: none;
        background: transparent;
    }
    
    #chat-input:focus {
        border: none;
    }

    /* Dynamic states */
    .input-disabled {
        background: $error-muted;
    }
    
    #bottom-zone {
        height: 1;
        color: $text-muted;
        background: $surface;
        padding: 0 1;
    }
    """
    
    def __init__(self, config: Dict[str, Any] = None, thread_id: str = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or {}
        self.thread_id = thread_id
        self.pending_approval_data: Optional[Dict[str, Any]] = None
        self.pending_command_confirmation: Optional[Dict[str, Any]] = None
        self.verbose: bool = False
        self._notice_timer = None
        self._stream_buffer: str = ""
        self._stream_active: bool = False
        self._interrupt_requested: bool = False
        self._active_response = None

    def _safe_call(self, callback, *args, **kwargs):
        """Thread-safe call that doesn't crash if loop is not running."""
        try:
            if self._loop and self._loop.is_running():
                self.call_from_thread(callback, *args, **kwargs)
            else:
                callback(*args, **kwargs)
        except RuntimeError:
            callback(*args, **kwargs)

    def compose(self) -> ComposeResult:
        yield GimoHeader()
        with Horizontal(id="top-zone"):
            yield GraphWidget()
            with Vertical(id="sidebar"):
                yield EconomyWidget()
                yield NoticesWidget()
        with Vertical(id="middle-zone"):
            yield ChatLogWidget(id=CHAT_LOG_ID[1:], markup=True, wrap=True)
            with Container(id="chat-input-box"):
                yield Input(placeholder=">>> Send a message to GIMO...", id="chat-input")
        with Container(id="bottom-zone"):
            yield Static("EVENT STREAM: Ready.", id="event-stream")
        yield Footer()
        
    def on_mount(self) -> None:
        self.query_one(GraphWidget).border_title = "🌐 Graph Engine Topology"
        self.query_one(EconomyWidget).border_title = "💰 Telemetry & Quotas"
        self.query_one(NoticesWidget).border_title = "🔔 Canonical Notices"
        self.query_one("#middle-zone").border_title = f"💬 Workspace (Thread: {self.thread_id})"

        log = self.query_one(CHAT_LOG_ID, ChatLogWidget)
        log.write(f"[dim italic]Secure session initialized at {self.thread_id}[/dim italic]")
        
        # Start background polling loops (daemon-like)
        self.set_interval(5.0, self.update_status)
        
        # Initial fetch
        self.update_status()

    def action_refresh_all(self):
        self.update_status()

    def action_interrupt_or_quit(self) -> None:
        if self._stream_active:
            self._interrupt_requested = True
            response = self._active_response
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            self._write_event("Interrupt requested. Closing active turn...")
            self._write_log("[yellow]Interrupting active turn...[/yellow]")
            return
        self.exit()

    def action_clear_log(self) -> None:
        """Clear the chat log via hotkey."""
        self.query_one("#chat-log", ChatLogWidget).clear()

    def _write_log(self, text: str):
        log = self.query_one("#chat-log", ChatLogWidget)
        log.write(text)
        
    def _write_event(self, text: str):
        evt_stream = self.query_one("#event-stream", Static)
        evt_stream.update(f"EVENT STREAM: {text}")

    def action_dismiss_notice(self) -> None:
        """Dismiss active notice on Escape."""
        if self._notice_timer:
            self._notice_timer.stop()
            self._notice_timer = None
        self.query_one("#notices-content", Static).update("   No active notices.")

    def show_notice(self, text: str, style: str = "yellow", ttl: int = 30):
        icon = "⚠" if style == "yellow" else "✗" if style == "red" else "ℹ"
        lbl = self.query_one("#notices-content", Static)
        lbl.update(f"[{style}]{icon} {text}[/{style}]")
        
        if self._notice_timer:
            self._notice_timer.stop()
            self._notice_timer = None
            
        if ttl > 0:
            def clear_notice():
                lbl.update("   No active notices.")
                self._notice_timer = None
            self._notice_timer = self.set_timer(ttl, clear_notice)

    def _set_input_state(self, enabled: bool):
        """Locks or unlocks the chat input box depending on orchestrator state."""
        inp = self.query_one("#chat-input", Input)
        box = self.query_one("#chat-input-box")
        if enabled:
            inp.disabled = False
            inp.placeholder = ">>> Send a message to GIMO..."
            box.remove_class("input-disabled")
            inp.focus()
        else:
            inp.disabled = True
            inp.placeholder = "GIMO is processing..."
            box.add_class("input-disabled")

    def _build_terminal_command_context(self) -> TerminalCommandContext:
        workspace_root = str(self.config.get("repository", {}).get("workspace_root") or self.config.get("workspace_root") or ".")
        return TerminalCommandContext(
            config=self.config,
            workspace_root=workspace_root,
            thread_id=self.thread_id,
            api_request=_api_request,
            save_config=_save_config,
            git_command=lambda args: subprocess.run(
                ["git", *args],
                text=True,
                capture_output=True,
                check=False,
            ),
        )

    def _queue_command_confirmation(
        self,
        prompt: str,
        on_confirm: Callable[[], Any],
        cancel_message: str,
    ) -> None:
        self.pending_command_confirmation = {
            "on_confirm": on_confirm,
            "cancel_message": cancel_message,
        }
        self._write_log(prompt)
        self._write_event("Awaiting command confirmation.")
        self._set_input_state(True)
        self.query_one("#chat-input", Input).placeholder = ">>> Type 'Y' to confirm or 'N' to cancel..."

    @work(thread=True)
    def _run_command_confirmation(self, on_confirm: Callable[[], Any]) -> None:
        try:
            on_confirm()
        finally:
            self._safe_call(self._set_input_state, True)

    @work(thread=True)
    def execute_slash_command(self, raw_command: str) -> None:
        try:
            parts = raw_command.split(maxsplit=1)
            command = parts[0]
            argument = parts[1].strip() if len(parts) > 1 else ""
            context = self._build_terminal_command_context()
            surface = TextualTerminalSurface(self)
            callbacks = build_terminal_command_callbacks(context, surface)
            handled, outcome = cli_commands.dispatch_slash_command(command, argument, callbacks)
            if handled and command not in {"/help", "/workspace", "/thread", "/clear", "/exit", "/quit", "/undo", "/diff", "/tokens", "/reset"}:
                self.update_status()
            if handled and isinstance(outcome, TerminalCommandOutcome) and outcome.should_exit:
                self._safe_call(self.exit)
        finally:
            self._safe_call(self._set_input_state, True)

    def _apply_status_snapshot(self, payload: dict[str, Any]) -> None:
        repo = payload.get("repo", "?")
        branch = payload.get("branch", "?")
        provider = payload.get("active_provider", "?")
        model = payload.get("active_model", "?")
        perm = payload.get("permissions", "suggest")
        budget = payload.get("budget_status", "ok")
        ctx = payload.get("context_status", "0%")
        msg = f"REPO: {repo} | BRANCH: {branch} | MODEL: {model} | PERM: {perm} | BUDGET: {budget} | CTX: {ctx}"
        self._update_header(msg)

        graph_text = (
            f"Repo: [bold]{repo}[/bold] ({branch})\n"
            f"Orchestrator: [cyan]{provider}[/cyan]\n"
            f"Model: [dim]{model}[/dim]"
        )
        self._update_graph_widget(graph_text)

        alerts = payload.get("alerts", [])
        if not isinstance(alerts, list) or not alerts:
            self._update_notices_widget(NO_NOTICES_MSG)
        else:
            lines: list[str] = []
            for notice in alerts:
                if isinstance(notice, dict):
                    level = notice.get("level", "info")
                    message = notice.get("message", "")
                else:
                    level = "warning"
                    message = str(notice)
                icon = "!" if level == "warning" else "x" if level == "error" else "i"
                color = "yellow" if level == "warning" else "red" if level == "error" else "blue"
                lines.append(f"[{color}]{icon} {message}[/{color}]")
            self._update_notices_widget("\n".join(lines))

        budget_pct = payload.get("budget_percentage", 100.0)
        if not isinstance(budget_pct, (int, float)):
            budget_pct = 100.0
        color = get_budget_color(budget_pct)
        bar_len = 20
        fill = min(int(((100 - budget_pct) / 100) * bar_len), bar_len)
        bar = "█" * fill + "░" * (bar_len - fill)
        telemetry_text = f"Global Budget Consumption\n[{color}]{bar}[/{color}] {100 - budget_pct:.1f}% used\n"
        self._update_eco_widget(telemetry_text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        if not val:
            return
            
        event.input.value = ""
        
        # Handle pending HITL approval
        if self.pending_approval_data:
            from cli_parsers import parse_yes_no
            approved = parse_yes_no(val)
            tool_call_id = self.pending_approval_data.get("tool_call_id")
            self.pending_approval_data = None
            
            color = "green" if approved else "red"
            status = "APPROVED" if approved else "DENIED"
            self._write_log(f"[{color}]> Tool execution {status}[/{color}]")
            
            # Lock input until stream yields next step
            self._set_input_state(False)
            self.submit_approval(tool_call_id, approved)
            return

        if self.pending_command_confirmation:
            from cli_parsers import parse_yes_no

            pending = self.pending_command_confirmation
            self.pending_command_confirmation = None
            approved = parse_yes_no(val)
            if not approved:
                self._write_log(str(pending["cancel_message"]))
                return
            self._set_input_state(False)
            self._run_command_confirmation(pending["on_confirm"])
            return

        if val.startswith("/"):
            self._set_input_state(False)
            self.execute_slash_command(val)
            return

        # Normal chat
        self._write_log(Panel(val, title="You", border_style="bold blue", padding=(0,1)))
        
        # Lock UI and Start streaming
        self._set_input_state(False)
        self._write_event("Sending secure chat request...")
        self.fetch_stream(val)

    @work(exclusive=True, thread=True)
    def fetch_stream(self, user_input: str) -> None:
        base_url, timeout_seconds = _api_settings(self.config)
        auth_token = resolve_token("operator", self.config)
        headers = {"Accept": "text/event-stream", "X-GIMO-Surface": "tui"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        self._stream_active = True
        self._interrupt_requested = False
        self._active_response = None

        try:
            stream_timeout = httpx.Timeout(
                connect=timeout_seconds,
                read=600.0,
                write=timeout_seconds,
                pool=timeout_seconds,
            )
            with httpx.Client(timeout=stream_timeout) as client:
                with client.stream(
                    "POST",
                    f"{base_url}/ops/threads/{self.thread_id}/chat/stream",
                    json={"content": user_input},
                    headers=headers,
                ) as response:
                    self._active_response = response
                    if response.status_code != 200:
                        self.call_from_thread(self._write_log, f"[bold red]HTTP {response.status_code}:[/bold red] {response.read().decode('utf-8', errors='ignore')}")
                        self.call_from_thread(self._set_input_state, True)
                        return
                    self._process_sse_stream(response)
        except Exception as e:
            self.call_from_thread(self._write_log, f"[bold red]Network Error:[/bold red] {e}")
            self.call_from_thread(self._set_input_state, True)
        finally:
            self._active_response = None
            self._stream_active = False
            self._interrupt_requested = False

    def _process_sse_stream(self, response) -> None:
        current_event_type = "message"
        self._stream_buffer = ""
        for line in response.iter_lines():
            if self._interrupt_requested:
                break
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
                self._handle_sse_event(current_event_type, data)
            except json.JSONDecodeError:
                continue
                
        # Final flush
        if getattr(self, "_stream_buffer", ""):
            self.call_from_thread(self._write_log, self._stream_buffer)
            self._stream_buffer = ""
            
        # Ensure UI unlocks
        self.call_from_thread(self._set_input_state, True)

    def _handle_sse_event(self, evt: str, data: dict) -> None:
        if evt == "text_delta":
            self._stream_buffer += data.get("content", "")
            return
            
        # Flush buffer before any distinct UI element
        if self._stream_buffer:
            self._safe_call(self._write_log, self._stream_buffer)
            self._stream_buffer = ""

        # DEBUG MODE: Raw SSE/events
        if self.verbose and evt != "text_delta":
            raw_str = str(json.dumps(data, ensure_ascii=False))
            preview = raw_str[:121] + "..." if len(raw_str) > 120 else raw_str
            self._safe_call(self._write_log, f"  [dim blue]SSE Event:[/dim blue] [dim]{evt}[/dim] -> [dim italic]{preview}[/dim italic]")

        if evt == "tool_call_start":
            tool_name = data.get("tool_name", "?")
            args = data.get("arguments", {})
            
            # FOCUS MODE: Concise tool summary
            if not self.verbose:
                items = list(args.items())
                slice_items = items[:3]
                arg_summary = " ".join([f"{k}={str(v)[:20]}" for k, v in slice_items])
                self._safe_call(self._write_log, f"\n  [dim]▸[/dim] [bold]{tool_name}[/bold] {arg_summary}...")
            else:
                # DEBUG MODE: Payloads/Topology
                self._safe_call(self._write_log, f"\n  [dim]▸ [bold]{tool_name}[/bold] {json.dumps(args, ensure_ascii=False)}")
            
            self._safe_call(self._write_event, f"Active Tool: {tool_name}")
            
        elif evt == "tool_approval_required":
            self._safe_call(self._require_approval, data)
            
        elif evt == "tool_call_end":
            status = data.get("status", "error")
            duration = data.get("duration", 0.0)
            symbol = "[bold green]✓[/bold green]" if status == "success" else "[bold red]✗[/bold red]"
            
            # FOCUS/DEBUG: timings
            self._safe_call(self._write_log, f"    {symbol} [dim]{duration:.1f}s[/dim]\n")
            self._safe_call(self._write_event, f"Processed Tool: {status}")
            
        elif evt == "done":
            self._safe_call(self._write_event, "Response complete. Awaiting input.")
            self._safe_call(self._set_input_state, True)
            self.update_status()
                
        elif evt == "error":
            self._safe_call(self._write_log, f"\n[bold red]Orchestrator Error:[/bold red] {data.get('message', 'Unknown')}\n")
            self._safe_call(self._set_input_state, True)

        elif evt == "session_start":
            mood = data.get("mood", "neutral")
            mood_icon = {"positive": "+", "negative": "!", "neutral": "~"}.get(mood, "~")
            self._safe_call(self._write_event, f"Session started (mood: {mood_icon})")

        elif evt == "user_question":
            question = data.get("question", "")
            options = data.get("options", [])
            context = data.get("context", "")
            parts = [f"[bold yellow]{question}[/bold yellow]"]
            if context:
                parts.append(f"[dim]{context}[/dim]")
            if options:
                parts.append("Options: " + ", ".join(str(o) for o in options))
            self._safe_call(self._write_log, Panel(
                "\n".join(parts),
                title="Agent Question",
                border_style="yellow",
            ))

        elif evt == "plan_proposed":
            title = data.get("title", "Proposed Plan")
            steps = data.get("steps", [])
            lines = [f"[bold]{title}[/bold]"]
            for i, step in enumerate(steps, 1):
                desc = step.get("description", str(step)) if isinstance(step, dict) else str(step)
                lines.append(f"  {i}. {desc}")
            self._safe_call(self._write_log, Panel(
                "\n".join(lines),
                title="Plan Proposed",
                border_style="cyan",
            ))
            self._safe_call(self._write_event, "Plan proposed — awaiting approval.")
            self._safe_call(self._set_input_state, True)
            inp = self.query_one("#chat-input", Input)
            inp.placeholder = ">>> Type 'approve' or 'reject'..."

        elif evt == "confirmation_required":
            tool_name = data.get("tool_name", "?")
            message = data.get("message", "")
            self._safe_call(self._write_log, Panel(
                f"{message}\n\nTool: [bold]{tool_name}[/bold]",
                title="Confirmation Required",
                border_style="yellow",
            ))
            self.pending_approval_data = data
            self._safe_call(self._set_input_state, True)
            inp = self.query_one("#chat-input", Input)
            inp.placeholder = ">>> Type 'Y' to confirm or 'N' to deny..."

        elif evt == "context_request_pending":
            self._safe_call(self._write_event, "Context request pending...")

    def _render_tui_post_run_report(self, run_data: dict, usage: dict):
        """Render a compact version of the CLI post-run report in the TUI log."""
        goal = run_data.get("goal") or "n/a"
        tools = len(run_data.get("tools_used", [])) if "tools_used" in run_data else 0
        diff = len(run_data.get("modified_files", [])) if "modified_files" in run_data else 0
        cost = usage.get("cost_usd", 0.0)
        dur = run_data.get("duration", 0.0)
        
        report = (
            f"[bold green]✓ Task Complete[/bold green]\n"
            f"  Goal: {goal}\n"
            f"  Changes: {diff} files, {tools} tools\n"
            f"  Cost: ${cost:.4f}  |  Duration: {dur:.1f}s"
        )
        self._write_log(Panel(report, border_style="green", padding=(0,1)))

    def _require_approval(self, data: dict):
        tool_name = data.get("tool_name", "?")
        args = json.dumps(data.get("arguments", {}), indent=2, ensure_ascii=False)
        self._write_log(Panel(
            f"Target Tool: [bold]{tool_name}[/bold]\n\nPayload:\n{args}",
            title="[bold red]⚠ HIGH RISK: Manual Approval Required (Y/N)[/bold red]",
            border_style="red"
        ))
        self.pending_approval_data = data
        self._write_event(f"Awaiting human-in-the-loop approval for {tool_name}")
        # Unlock input specifically so user can type Y/N
        self._set_input_state(True)
        # Give a special placeholder
        inp = self.query_one("#chat-input", Input)
        inp.placeholder = ">>> Type 'Y' to approve or 'N' to deny..."

    @work(thread=True)
    def submit_approval(self, tool_call_id: str, approved: bool):
        base_url, timeout_seconds = _api_settings(self.config)
        auth_token = resolve_token("operator", self.config)
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                res = client.post(
                    f"{base_url}/ops/threads/{self.thread_id}/approve-tool",
                    params={"tool_call_id": tool_call_id, "approved": str(approved).lower()},
                    headers=headers
                )
                if res.status_code != 200:
                    self._safe_call(self._write_log, f"[bold red]Approval failed (HTTP {res.status_code})[/bold red]")
        except Exception as e:
            self._safe_call(self._write_log, f"[bold red]Approval network error:[/bold red] {e}")
        finally:
            self._safe_call(self._set_input_state, True)

    @work(thread=True)
    def update_status(self):
        """Fetch canonical status snapshot and update all widgets (Invariant: authoritative_contracts)."""
        try:
            status, payload = fetch_operator_status_snapshot(self.config, _api_request)
            if status == 200 and isinstance(payload, dict):
                self._safe_call(self._apply_status_snapshot, payload)
            else:
                self._safe_call(self._update_header, "REPO: ? | BRANCH: ? | MODEL: ? | PERM: ? | BUDGET: ? | CTX: ?")
                self._safe_call(self._update_graph_widget, "[yellow]Status bridge disconnected.[/yellow]")
        except Exception as e:
            self._safe_call(self._update_graph_widget, f"[red]Status Error: {e}[/red]")

    def _refresh_topology_logic(self):
        """Backward-compatible topology refresh entry point for tests and legacy callers."""
        try:
            status, payload = _api_request(self.config, "GET", "/ops/operator/status")
            if status != 200 or not isinstance(payload, dict):
                self._safe_call(self._update_graph_widget, "[yellow]Status bridge disconnected.[/yellow]")
                return

            repo = payload.get("repo", "?")
            branch = payload.get("branch", "?")
            provider = payload.get("active_provider", "?")
            model = payload.get("active_model", "?")
            text = (
                f"ðŸ“ Repo: [bold]{repo}[/bold] ({branch})\n"
                f"ðŸ§  Orchestrator: [cyan]{provider}[/cyan]\n"
                f"   Model: [dim]{model}[/dim]"
            )
            self._safe_call(self._update_graph_widget, text)
        except Exception as e:
            self._safe_call(self._update_graph_widget, f"[red]Status Error: {e}[/red]")

    @work(thread=True)
    def update_notices(self):
        """Backward-compatible notice refresh that consumes the canonical backend notice feed."""
        try:
            status, payload = fetch_operator_status_snapshot(self.config, _api_request)
            if status != 200 or not isinstance(payload, dict):
                self._safe_call(self._update_notices_widget, NO_NOTICES_MSG)
                return
            self._safe_call(self._apply_status_snapshot, payload)
            return
            status, payload = _api_request(self.config, "GET", "/ops/notices")
            if status != 200 or not isinstance(payload, list) or not payload:
                self._safe_call(self._update_notices_widget, NO_NOTICES_MSG)
                return

            lines = []
            for notice in payload:
                lvl = notice.get("level", "info")
                msg = notice.get("message", "")
                icon = "âš " if lvl == "warning" else "âœ—" if lvl == "error" else "â„¹"
                color = "yellow" if lvl == "warning" else "red" if lvl == "error" else "blue"
                lines.append(f"[{color}]{icon} {msg}[/{color}]")
            self._safe_call(self._update_notices_widget, "\n".join(lines))
        except Exception as e:
            self._safe_call(self._update_notices_widget, f"[red]Notice Error: {e}[/red]")

    def _update_header(self, text: str):
        self.query_one("#header-text", Static).update(text)

    def _update_notices_widget(self, text: str):
        self.query_one(NOTICES_CONTENT_ID, Static).update(text)

    def _update_graph_widget(self, text: str):
        lbl = self.query_one(GRAPH_CONTENT_ID, Static)
        lbl.update(text)

    def _update_eco_widget(self, text: str):
        lbl = self.query_one(ECO_CONTENT_ID, Static)
        lbl.update(text)

if __name__ == "__main__":
    app = GimoApp()
    app.run()
