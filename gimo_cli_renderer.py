"""GIMO CLI visual renderer for agentic chat sessions.

Provides Rich-based rendering for tool calls, LLM responses, and session state.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text


class ChatRenderer:
    """Renders chat session visuals to the terminal."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    def render_session_header(
        self,
        *,
        provider_id: str,
        model: str,
        workspace: str,
        thread_id: str,
    ) -> None:
        info = "\n".join([
            f"  orchestrator: {model} ({provider_id})",
            f"  workspace: {workspace}",
            f"  thread: {thread_id}",
        ])
        self.console.print(Panel(info, title="GIMO", border_style="cyan"))
        self.console.print()

    def render_thinking(self) -> Any:
        """Return a status context manager for the 'thinking' spinner."""
        return self.console.status("[dim]Thinking...[/dim]", spinner="dots")

    def render_tool_call(self, tool: Dict[str, Any]) -> None:
        name = tool.get("name", "unknown")
        status = tool.get("status", "success")
        duration = tool.get("duration", 0.0)
        risk = tool.get("risk", "LOW")
        args = tool.get("arguments", {})

        # Build arg summary (short)
        arg_parts: List[str] = []
        for key, val in args.items():
            val_str = str(val)
            if len(val_str) > 40:
                val_str = val_str[:37] + "..."
            arg_parts.append(f"{key}={val_str}")
        arg_summary = " ".join(arg_parts[:3])

        if status == "success":
            symbol = "[green]\u2713[/green]"
            style = "dim"
        elif status == "error":
            symbol = "[red]\u2717[/red]"
            style = "dim red"
        else:
            symbol = "[yellow]\u2298[/yellow]"
            style = "dim yellow"

        line = Text.from_markup(
            f"  [dim]\u25b8[/dim] {name} {arg_summary}  {symbol} [dim]{duration:.1f}s[/dim]"
        )
        self.console.print(line)

        # Show detail for write operations
        if name in ("write_file", "search_replace", "patch_file") and status == "success":
            if name == "search_replace":
                old = str(args.get("old_text", ""))[:60]
                new = str(args.get("new_text", ""))[:60]
                self.console.print(f"    [dim]old: {old}[/dim]")
                self.console.print(f"    [dim]new: {new}[/dim]")
            elif name == "write_file":
                path = args.get("path", "")
                content = args.get("content", "")
                self.console.print(f"    [dim]{path} ({len(content)} chars)[/dim]")

    def render_tool_calls(self, tool_calls: List[Dict[str, Any]]) -> None:
        for tc in tool_calls:
            self.render_tool_call(tc)

    def render_response(self, response: str) -> None:
        if not response:
            return
        self.console.print()
        self.console.print(Markdown(response))

    def render_footer(self, usage: Dict[str, Any]) -> None:
        tokens = usage.get("total_tokens", 0)
        cost = usage.get("cost_usd", 0.0)
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        parts = []
        if tokens:
            parts.append(f"{tokens:,} tokens")
        if cost:
            parts.append(f"${cost:.4f}")

        if parts:
            self.console.print()
            self.console.print(Rule(" \u00b7 ".join(parts), style="dim"))

    def render_error(self, message: str) -> None:
        self.console.print(Panel(message, title="Error", border_style="red"))

    def render_preflight_error(self, message: str, *, hint: str = "") -> None:
        content = message
        if hint:
            content += f"\n\n[dim]{hint}[/dim]"
        self.console.print(Panel(content, title="GIMO", border_style="red"))

    def get_user_input(self) -> str:
        """Prompt user for input."""
        try:
            return self.console.input("[bold cyan]> [/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            return "/exit"
