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

class GraphWidget(Static):
    """Renders the agentic swarm topology."""
    def compose(self) -> ComposeResult:
        yield Static("   Loading topology...", classes="content-area", id="graph-content")

class EconomyWidget(Static):
    """Renders the token usage and limits."""
    def compose(self) -> ComposeResult:
        yield Static("   Fetching telemetry...", classes="content-area", id="eco-content")

class NoticesWidget(Static):
    """Renders temporary system notices."""
    def compose(self) -> ComposeResult:
        yield Static("   No active notices.", classes="content-area", id="notices-content")

class ChatLogWidget(RichLog):
    """Renders the chat history cleanly."""
    pass

CHAT_LOG_ID = "#chat-log"

class GimoApp(App):
    """GIMO Orchestrator Textual App (Production Ready)."""
    
    TITLE = "GIMO Orchestrator"
    
    BINDINGS = [
        Binding("ctrl+c,ctrl+q", "quit", "Quit Session", show=True),
        Binding("ctrl+l", "clear_log", "Clear Chat", show=True),
        Binding("escape", "dismiss_notice", "Dismiss Notice", show=False),
    ]
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    #top-zone {
        height: 35%;
        margin-bottom: 1;
    }
    
    GraphWidget, EconomyWidget, NoticesWidget {
        height: 100%;
        border: heavy $background;
        background: $boost;
    }
    
    GraphWidget {
        width: 50%;
        border-title-color: $accent;
    }
    
    EconomyWidget {
        width: 25%;
        border-title-color: $success;
        margin-left: 1;
    }

    NoticesWidget {
        width: 25%;
        border-title-color: $warning;
        margin-left: 1;
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, icon="🖧")
        with Horizontal(id="top-zone"):
            yield GraphWidget()
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
        self.query_one(NoticesWidget).border_title = "🔔 System Notices"
        self.query_one("#middle-zone").border_title = f"💬 Workspace (Thread: {self.thread_id})"

        log = self.query_one(CHAT_LOG_ID, ChatLogWidget)
        log.write(f"[dim italic]Secure session initialized at {self.thread_id}[/dim italic]")
        
        # Start background polling loops (daemon-like)
        self.set_interval(4.0, self.update_telemetry)
        self.set_interval(5.0, self.update_topology)
        
        # Initial fetch
        self.update_telemetry()
        self.update_topology()

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
                    self.update_telemetry()
                    self.update_topology()
                    self.call_from_thread(self._write_log, "[green]Requested status refresh.[/green]")
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
                    self.update_topology()
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
                    self.call_from_thread(self._write_log, "[dim]Token data available via /tokens in the CLI interactive chat.[/dim]")
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
                    st, py = _api_request(self.config, "POST", f"/ops/threads/{self.thread_id}/config", json_body={"hitl_mode": val})
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
            self.call_from_thread(self._write_log, self._stream_buffer)
            self._stream_buffer = ""

        if self.verbose and evt != "text_delta":
            import json
            raw_str = json.dumps(data, ensure_ascii=False)
            preview = raw_str[:120] + "..." if len(raw_str) > 120 else raw_str
            self.call_from_thread(self._write_log, f"  [dim blue]SSE Event:[/dim blue] [dim]{evt}[/dim] -> [dim italic]{preview}[/dim italic]")

        if evt == "tool_call_start":
            tool_name = data.get("tool_name", "?")
            args = str(data.get("arguments", {}))[:60]
            risk = data.get("risk", "LOW")
            if risk == "HIGH":
                risk_col = "red"
            elif risk == "MEDIUM":
                risk_col = "yellow"
            else:
                risk_col = "green"
                
            suffix = "[dim]...[/dim]"
            if self.verbose:
                suffix = f"\n    [dim italic]{json.dumps(data.get('arguments', {}), ensure_ascii=False)}[/dim italic]"

            self.call_from_thread(self._write_log, f"\n  [dim]▸ [bold]{tool_name}[/bold] {args}... [{risk_col}]{risk}[/{risk_col}] {suffix}")
            self.call_from_thread(self._write_event, f"Active Tool: {tool_name}")
            
        elif evt == "tool_approval_required":
            self.call_from_thread(self._require_approval, data)
            
        elif evt == "tool_call_end":
            status = data.get("status", "error")
            duration = data.get("duration", 0.0)
            symbol = "[bold green]✓[/bold green]" if status == "success" else "[bold red]✗[/bold red]"
            self.call_from_thread(self._write_log, f"    {symbol} [dim]{duration:.1f}s[/dim]\n")
            self.call_from_thread(self._write_event, f"Processed Tool: {status}")
            
        elif evt == "done":
            self.call_from_thread(self._write_event, "Response complete. Awaiting input.")
            self.call_from_thread(self._set_input_state, True)
            
            usage = data.get("usage", {})
            ctx_pct = usage.get("context_window_pct", 0)
            if ctx_pct > 70:
                self.call_from_thread(self.show_notice, f"Context window high: {ctx_pct:.1f}%", "yellow", 30)
                
            cost = usage.get("cost_usd", 0)
            budget_limit = float(self.config.get("orchestrator", {}).get("budget_limit_usd") or 0)
            if budget_limit > 0 and (cost / budget_limit) > 0.8:
                self.call_from_thread(self.show_notice, f"Budget critical: ${cost:.2f}/${budget_limit:.2f}", "red", 0)
            
        elif evt == "error":
            self.call_from_thread(self._write_log, f"\n[bold red]Orchestrator Error:[/bold red] {data.get('message', 'Unknown')}\n")
            self.call_from_thread(self._set_input_state, True)

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
                    self.call_from_thread(self._write_log, f"[bold red]Approval failed (HTTP {res.status_code})[/bold red]")
        except Exception as e:
            self.call_from_thread(self._write_log, f"[bold red]Approval network error:[/bold red] {e}")
        finally:
            # We must wait for the orchestrator to resume streaming, but the stream is already killed by the pause.
            # In a real setup, hitting approve might require a new POST /chat to resume.
            # But according to GIMO design, the SSE stream resumes or requires polling. 
            # We unlock input so user doesn't get stuck.
            self.call_from_thread(self._set_input_state, True)

    @work(thread=True)
    def update_telemetry(self):
        """Fetch global budget/usage stats robustly."""
        try:
            status, payload = _api_request(self.config, "GET", "/ops/forecast")
            if status == 200 and isinstance(payload, list):
                for f in payload:
                    if f.get("scope") == "global":
                        text = self._format_telemetry(f)
                        self.call_from_thread(self._update_eco_widget, text)
                        return
            self.call_from_thread(self._update_eco_widget, "Telemetry unavailable.")
        except Exception as e:
            self.call_from_thread(self._update_eco_widget, f"[red]Telemetry Error: {e}[/red]")

    def _format_telemetry(self, f: dict) -> str:
        spend = f.get("current_spend", 0.0)
        limit = f.get("limit")
        rem_pct = f.get("remaining_pct")
        
        if not limit:
            return f"Spent: [bold green]${spend:.4f}[/bold green] (Unmetered)"
            
        bar_len = 20
        fill = min(int((spend / limit) * bar_len), bar_len)
        bar = "█" * fill + "░" * (bar_len - fill)
        from cli_policies import get_budget_color
        color = get_budget_color(rem_pct)
        
        return f"Global Budget Tracking\n[{color}]{bar}[/{color}] [bold]{spend:.2f}[/bold] / {limit:.2f} USD\n"

    @work(thread=True)
    def update_topology(self):
        """Fetch worker pool to show Graph topology robustly."""
        try:
            status, payload = _api_request(self.config, "GET", "/ops/provider")
            if status == 200 and isinstance(payload, dict):
                providers = payload.get("providers", {})
                lines = []
                for pid, pdata in providers.items():
                    roles = pdata.get("role_bindings", [])
                    role_str = roles[0].upper() if roles else "GENERIC WORKER"
                    ptype = str(pdata.get("provider_type", "unknown")).upper()
                    lines.append(f"🟢 [bold cyan]{pid}[/bold cyan] [dim]({role_str} - {ptype})[/dim]")
                
                self.call_from_thread(self._update_graph_widget, "\n".join(lines) if lines else "[dim]No active workers allocated.[/dim]")
            else:
                self.call_from_thread(self._update_graph_widget, "[yellow]Topology bridge disconnected.[/yellow]")
        except Exception as e:
            self.call_from_thread(self._update_graph_widget, f"[red]Topology Error: {e}[/red]")

    def _update_graph_widget(self, text: str):
        lbl = self.query_one("#graph-content", Static)
        lbl.update(text)

    def _update_eco_widget(self, text: str):
        lbl = self.query_one("#eco-content", Static)
        lbl.update(text)

if __name__ == "__main__":
    app = GimoApp()
    app.run()
