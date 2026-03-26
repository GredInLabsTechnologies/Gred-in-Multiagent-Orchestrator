import json
import httpx
from typing import Any, Dict, Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Input, RichLog
from rich.text import Text
from rich.panel import Panel

# Re-use critical logic from gimo 
from gimo import _api_settings, _resolve_token, _api_request

# Constants to avoid literal duplication
CHAT_LOG_ID = "#chat-log"
NOTICES_CONTENT_ID = "#notices-content"
GRAPH_CONTENT_ID = "#graph-content"
ECO_CONTENT_ID = "#eco-content"
NO_NOTICES_MSG = "   No active notices."

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
        Binding("ctrl+c", "quit", "Quit Session", show=True),
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
        self.verbose: bool = False
        self._notice_timer = None
        self._stream_buffer: str = ""

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
            
        # Handle slash commands natively 
        if val.startswith("/"):
            from cli_commands import dispatch_slash_command
            from gimo import _api_request
            from rich.panel import Panel

            def show_help():
                from cli_commands import get_help_text
                self._write_log(Panel(get_help_text(), title="Chat Commands", border_style="cyan"))

            def show_workspace():
                self._write_log(Panel(str(self.config.get("workspace_root", "Unknown")), title="Workspace", border_style="blue"))

            def show_thread():
                self._write_log(Panel(str(self.thread_id), title="Thread", border_style="blue"))

            def unknown_command(cmd: str):
                self._write_log(f"[yellow]Unknown command: {cmd}. Use /help.[/yellow]")

            @work(thread=True)
            def do_slash_fetch(action: str):
                if action == "status":
                    self.update_status()
                    self.call_from_thread(self._write_log, "[green]Status refreshed.[/green]")
                elif action == "provider_list":
                    st, py = _api_request(self.config, "GET", "/ops/provider")
                    if st == 200 and isinstance(py, dict):
                        lines = ["[cyan]Configured Providers:[/cyan]"]
                        for pid, pdata in py.get("providers", {}).items():
                            lines.append(f" - [bold]{pid}[/bold] (Type: {pdata.get('type', 'unknown')})")
                        self.call_from_thread(self._write_log, Panel("\n".join(lines)))
                    else:
                        self.call_from_thread(self._write_log, f"[red]Failed to fetch providers ({st})[/red]")
                elif action == "models":
                    st, py = _api_request(self.config, "GET", "/ops/provider/models")
                    if st == 200 and isinstance(py, list):
                        lines = ["[cyan]Available Models:[/cyan]"]
                        for item in py:
                            m = item.get("id", str(item)) if isinstance(item, dict) else str(item)
                            lines.append(f" - {m}")
                        self.call_from_thread(self._write_log, Panel("\n".join(lines)))
                    else:
                        self.call_from_thread(self._write_log, f"[red]Failed to fetch models: {py}[/red]")
                elif action == "workers":
                    self.update_status()
                    self.call_from_thread(self._write_log, "[green]Detailed workers topology refreshed in sidebar.[/green]")
                # ── P0 new actions ────────────────────────────────────────────
                elif action == "undo":
                    import subprocess as _sp
                    res = _sp.run(["git", "revert", "--no-edit", "HEAD"], capture_output=True, text=True, check=False)
                    if res.returncode == 0:
                        self.call_from_thread(self._write_log, Panel(res.stdout.strip() or "Revert successful.", title="✓ /undo", border_style="green"))
                    else:
                        self.call_from_thread(self._write_log, Panel(res.stderr.strip() or "Revert failed.", title="✗ /undo failed", border_style="red"))
                elif action == "reset":
                    st, py = _api_request(self.config, "POST", f"/ops/threads/{self.thread_id}/reset")
                    if st in {200, 204}:
                        self.call_from_thread(self._write_log, "[green]✓ Contexto del thread reiniciado.[/green]")
                    else:
                        self.call_from_thread(self._write_log, f"[red]Reset failed ({st}): {py}[/red]")
                elif action == "tokens":
                    self.call_from_thread(self._write_log, "[dim]Token data available via /tokens in the CLI interactive chat o consultable vía logs en background.[/dim]")
                elif action == "diff":
                    st, py = _api_request(self.config, "GET", "/ops/files/diff")
                    if st == 200:
                        diff_text = py.get("diff") or py.get("content") or str(py) if isinstance(py, dict) else str(py)
                        self.call_from_thread(self._write_log, Panel(diff_text or "[dim]No diff.[/dim]", title="📄 /diff", border_style="yellow"))
                    else:
                        self.call_from_thread(self._write_log, f"[red]Diff unavailable ({st}): {py}[/red]")
                elif action.startswith("effort:"):
                    val = action.split(":", 1)[1]
                    st, py = _api_request(self.config, "POST", f"/ops/threads/{self.thread_id}/config", json_body={"effort": val})
                    msg = f"[green]✓ Esfuerzo: {val}[/green]" if st in {200, 204} else f"[red]effort failed ({st}): {py}[/red]"
                    self.call_from_thread(self._write_log, msg)
                elif action.startswith("permissions:"):
                    val = action.split(":", 1)[1]
                    st, py = _api_request(self.config, "POST", f"/ops/threads/{self.thread_id}/config", json_body={"permissions": val})
                    msg = f"[green]✓ Permisos: perm:{val}[/green]" if st in {200, 204} else f"[red]permissions failed ({st}): {py}[/red]"
                    self.call_from_thread(self._write_log, msg)
                elif action.startswith("add:"):
                    path_val = action.split(":", 1)[1]
                    st, py = _api_request(self.config, "POST", f"/ops/threads/{self.thread_id}/context/add", json_body={"path": path_val})
                    msg = f"[green]✓ Añadido: {path_val}[/green]" if st in {200, 201} else f"[red]add failed ({st}): {py}[/red]"
                    self.call_from_thread(self._write_log, msg)
                elif action == "debug":
                    self.verbose = not self.verbose
                    self.call_from_thread(self._write_log, f"[dim]Debug mode {'enabled' if self.verbose else 'disabled'}[/dim]")


            callbacks = {
                "show_help": show_help,
                "show_workspace": show_workspace,
                "show_thread": show_thread,
                "exit_session": self.exit,
                "handle_provider": lambda arg: do_slash_fetch("provider_list") if arg == "list" else self._write_log("[yellow]Only /provider list is supported in TUI.[/yellow]"),
                "list_models": lambda: do_slash_fetch("models"),
                "handle_model": lambda arg: self._write_log("[yellow]Model switching is only supported via interactive chat or UI settings.[/yellow]"),
                "show_workers": lambda: do_slash_fetch("workers"),
                "show_status": lambda: do_slash_fetch("status"),
                # ── P0 new commands ───────────────────────────────────────────
                "undo": lambda: do_slash_fetch("undo"),
                "clear_view": self.action_clear_log,
                "reset_context": lambda: do_slash_fetch("reset"),
                "show_tokens": lambda: do_slash_fetch("tokens"),
                "show_diff": lambda: do_slash_fetch("diff"),
                "set_effort": lambda val: do_slash_fetch(f"effort:{val}"),
                "set_permissions": lambda val: do_slash_fetch(f"permissions:{val}"),
                "add_file": lambda path: do_slash_fetch(f"add:{path}"),
                "toggle_debug": lambda: do_slash_fetch("debug"),
                "invalid_arg": lambda msg: self._write_log(f"[yellow]⚠ {msg}[/yellow]"),
                "unknown_command": unknown_command,
            }

            parts = val.split(maxsplit=1)
            cmd = parts[0]
            arg = parts[1] if len(parts) > 1 else ""
            is_cmd, _ = dispatch_slash_command(cmd, arg, callbacks)
            if is_cmd:
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
        auth_token = _resolve_token()
        headers = {"Accept": "text/event-stream"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

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
                    params={"content": user_input},
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        self.call_from_thread(self._write_log, f"[bold red]HTTP {response.status_code}:[/bold red] {response.read().decode('utf-8', errors='ignore')}")
                        self.call_from_thread(self._set_input_state, True)
                        return
                    self._process_sse_stream(response)
        except Exception as e:
            self.call_from_thread(self._write_log, f"[bold red]Network Error:[/bold red] {e}")
            self.call_from_thread(self._set_input_state, True)

    def _process_sse_stream(self, response) -> None:
        current_event_type = "message"
        self._stream_buffer = ""
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
            
            usage = data.get("usage", {})
            run_data = data.get("run_report", {})
            
            # FOCUS MODE: Post-run report
            if not self.verbose and (run_data or usage):
                self._safe_call(self._render_tui_post_run_report, run_data, usage)
                
            # Notices from usage/done
            ctx_pct = usage.get("context_window_pct", 0)
            if ctx_pct > 70:
                self._safe_call(self.show_notice, f"Context window high: {ctx_pct:.1f}%", "yellow", 30)
                
        elif evt == "error":
            self._safe_call(self._write_log, f"\n[bold red]Orchestrator Error:[/bold red] {data.get('message', 'Unknown')}\n")
            self._safe_call(self._set_input_state, True)

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
        auth_token = _resolve_token()
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
            status, payload = _api_request(self.config, "GET", "/ops/operator/status")
            if status == 200 and isinstance(payload, dict):
                repo = payload.get("repo", "?")
                branch = payload.get("branch", "?")
                provider = payload.get("active_provider", "?")
                model = payload.get("active_model", "?")
                perm = payload.get("permissions", "suggest")
                budget = payload.get("budget_status", "ok")
                ctx = payload.get("context_status", "0%")
                
                # 1. Update Header
                msg = f"REPO: {repo} | BRANCH: {branch} | MODEL: {model} | PERM: {perm} | BUDGET: {budget} | CTX: {ctx}"
                self._safe_call(self._update_header, msg)
                
                # 2. Update Graph
                text = (
                    f"📁 Repo: [bold]{repo}[/bold] ({branch})\n"
                    f"🧠 Orchestrator: [cyan]{provider}[/cyan]\n"
                    f"   Model: [dim]{model}[/dim]"
                )
                self._safe_call(self._update_graph_widget, text)

                # 3. Update Notices
                alerts = payload.get("alerts", [])
                if not alerts:
                    self._safe_call(self._update_notices_widget, NO_NOTICES_MSG)
                else:
                    lines = []
                    for n in alerts:
                        lvl = n.get("level", "info")
                        msg = n.get("message", "")
                        icon = "⚠" if lvl == "warning" else "✗" if lvl == "error" else "ℹ"
                        color = "yellow" if lvl == "warning" else "red" if lvl == "error" else "blue"
                        lines.append(f"[{color}]{icon} {msg}[/{color}]")
                    self._safe_call(self._update_notices_widget, "\n".join(lines))

                # 4. Update Telemetry (Budget Bar)
                budget_pct = payload.get("budget_percentage", 100.0)
                from cli_policies import get_budget_color
                color = get_budget_color(budget_pct)
                bar_len = 20
                fill = min(int(((100 - budget_pct) / 100) * bar_len), bar_len)
                bar = "█" * fill + "░" * (bar_len - fill)
                telemetry_text = f"Global Budget Consumption\n[{color}]{bar}[/{color}] {100-budget_pct:.1f}% used\n"
                self._safe_call(self._update_eco_widget, telemetry_text)

            else:
                self._safe_call(self._update_graph_widget, "[yellow]Status bridge disconnected.[/yellow]")
        except Exception as e:
            self._safe_call(self._update_graph_widget, f"[red]Status Error: {e}[/red]")

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
