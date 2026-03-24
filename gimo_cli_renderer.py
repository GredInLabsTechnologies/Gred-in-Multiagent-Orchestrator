"""GIMO CLI visual renderer for agentic chat sessions.

Provides Rich-based rendering for tool calls, LLM responses, and session state.
"""
from __future__ import annotations

import json
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

        from cli_policies import CODE_EDITING_TOOL_NAMES
        # Show detail for write operations
        if name in CODE_EDITING_TOOL_NAMES and status == "success":
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

    def render_tool_call_start(self, tool_name: str, args: dict, risk: str) -> None:
        """Render a tool call as it starts (streaming mode)."""
        risk_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}.get(risk, "dim")
        arg_parts = []
        for key, val in (args or {}).items():
            val_str = str(val)
            if len(val_str) > 40:
                val_str = val_str[:37] + "..."
            arg_parts.append(f"{key}={val_str}")
        arg_summary = " ".join(arg_parts[:3])
        self.console.print(
            f"  [dim]\u25b8[/dim] {tool_name} {arg_summary}  [{risk_color}]{risk}[/{risk_color}] [dim]...[/dim]"
        )

    def render_tool_call_result(self, tool_name: str, status: str, duration: float, risk: str) -> None:
        """Render tool call completion (streaming mode)."""
        if status == "success":
            symbol = "[green]\u2713[/green]"
        elif status == "denied":
            symbol = "[red]\u2298 DENIED[/red]"
        else:
            symbol = "[red]\u2717[/red]"
        self.console.print(f"    {symbol} [dim]{duration:.1f}s[/dim]")

    def render_hitl_prompt(self, tool_name: str, args: dict) -> bool:
        """Ask user for HITL approval. Returns True if approved."""
        self.console.print()
        self.console.print(Panel(
            f"[bold red]HIGH RISK[/bold red] tool requires approval:\n\n"
            f"  Tool: [bold]{tool_name}[/bold]\n"
            f"  Args: {json.dumps(args, indent=2, ensure_ascii=False)[:300]}",
            title="\u26a0 HITL Approval Required",
            border_style="red",
        ))
        try:
            answer = self.console.input("[bold yellow]Approve? (y/N): [/bold yellow]")
            from cli_parsers import parse_yes_no
            return parse_yes_no(answer)
        except (EOFError, KeyboardInterrupt):
            return False

    def render_streaming_text(self, text: str) -> None:
        """Render text content as it arrives during streaming."""
        if text:
            self.console.print(Markdown(text))

    def get_user_input(self) -> str:
        """Prompt user for input with slash command autocompletion."""
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.completion import Completer, Completion
            from prompt_toolkit.formatted_text import HTML
            from prompt_toolkit.styles import Style

            class SlashCommandCompleter(Completer):
                def get_completions(self, document, complete_event):
                    from cli_commands import get_autocomplete_dict
                    commands_dict = get_autocomplete_dict()
                    text = document.text_before_cursor
                    # Only complete if we're typing the first word and it starts with /
                    parts = text.split(" ")
                    if len(parts) == 1 and text.startswith("/"):
                        word = parts[0]
                        for cmd, desc in commands_dict.items():
                            if cmd.startswith(word):
                                yield Completion(
                                    cmd,
                                    start_position=-len(word),
                                    display=cmd,
                                    display_meta=desc
                                )

            if not hasattr(self, "_prompt_session") or not self._prompt_session:
                custom_style = Style.from_dict({
                    'completion-menu': 'bg:#0f1e24 #a0b2b8',
                    'completion-menu.completion': 'bg:#0f1e24 #e0e8eb',
                    'completion-menu.completion.current': 'bg:#1a3640 #ffffff bold',
                    'completion-menu.meta.completion': 'bg:#162b33 #9fc8cc',
                    'completion-menu.meta.completion.current': 'bg:#1e3f4a #ffffff bold',
                    'completion-menu.multi-column-meta': 'bg:#162b33 #9fc8cc',
                    'scrollbar.background': 'bg:#050a0c',
                    'scrollbar.button': 'bg:#2a505e',
                    'bottom-toolbar': 'bg:#1a3640 #e0e8eb',
                })
                # Add prompt_toolkit formatting resembling rich bold cyan >
                self._prompt_session = PromptSession(
                    completer=SlashCommandCompleter(),
                    style=custom_style
                )

            try:
                def get_toolbar():
                    if self.telemetry_html:
                        return HTML(self.telemetry_html)
                    return None
                
                result = self._prompt_session.prompt(
                    HTML("<b><ansicyan>&gt; </ansicyan></b>"),
                    bottom_toolbar=get_toolbar
                )
                return result.strip()
            except (EOFError, KeyboardInterrupt):
                return "/exit"
        except ImportError:
            # Fallback if prompt_toolkit is not installed
            try:
                return self.console.input("[bold cyan]> [/bold cyan]").strip()
            except (EOFError, KeyboardInterrupt):
                return "/exit"

    # ── P2: Conversational Planning Renderers ─────────────────────────────────

    def render_mood_indicator(self, mood: str) -> None:
        """Render the current agent mood."""
        mood_colors = {
            "neutral": "dim",
            "forensic": "blue",
            "executor": "green",
            "dialoger": "cyan",
            "creative": "magenta",
            "guardian": "red",
            "mentor": "yellow",
        }
        color = mood_colors.get(mood, "dim")
        self.console.print(f"[{color}][mood: {mood}][/{color}]")

    def render_user_question(self, question: str, options: List[str], context: str) -> None:
        """Render a question from the agent."""
        self.console.print()
        content_parts = [f"[bold]{question}[/bold]"]
        if context:
            content_parts.append(f"\n[dim]{context}[/dim]")
        if options:
            content_parts.append("\n\nSuggested answers:")
            for idx, opt in enumerate(options, 1):
                content_parts.append(f"  {idx}. {opt}")

        self.console.print(Panel(
            "\n".join(content_parts),
            title="\u2753 Question",
            border_style="cyan",
        ))

    def render_plan(self, plan: Dict[str, Any]) -> None:
        """Render a proposed execution plan."""
        title = plan.get("title", "Execution Plan")
        objective = plan.get("objective", "")
        tasks = plan.get("tasks", [])

        self.console.print()
        self.console.print(Panel(
            f"[bold]{title}[/bold]\n\n{objective}",
            title="\ud83d\udccb Plan Proposed",
            border_style="magenta",
        ))

        # Render tasks
        for idx, task in enumerate(tasks, 1):
            task_id = task.get("id", f"t{idx}")
            task_title = task.get("title", "Task")
            task_desc = task.get("description", "")
            mood = task.get("agent_mood", "neutral")
            rationale = task.get("agent_rationale", "")
            depends = task.get("depends_on", [])

            mood_emoji = {
                "forensic": "\ud83d\udd0d",
                "executor": "\u2699\ufe0f",
                "dialoger": "\ud83d\udcac",
                "creative": "\u2728",
                "guardian": "\ud83d\udee1\ufe0f",
                "mentor": "\ud83c\udfaf",
                "neutral": "\ud83e\udd16",
            }.get(mood, "\ud83e\udd16")

            task_parts = [f"[bold]{mood_emoji} {task_title}[/bold] (mood: {mood})"]
            if task_desc:
                task_parts.append(f"  {task_desc}")
            if rationale:
                task_parts.append(f"  [dim italic]Why: {rationale}[/dim italic]")
            if depends:
                task_parts.append(f"  [dim]Depends on: {', '.join(depends)}[/dim]")

            self.console.print()
            self.console.print("\n".join(task_parts))

        self.console.print()
        self.console.print(Rule("Review the plan above", style="dim magenta"))

    def get_plan_approval(self) -> str:
        """Prompt user to approve, reject, or modify a plan.

        Returns: "approve", "reject", or "modify"
        """
        self.console.print()
        self.console.print("[bold yellow]Approve this plan?[/bold yellow]")
        self.console.print("  [cyan]y[/cyan] = Approve and execute")
        self.console.print("  [red]n[/red] = Reject (ask agent to revise)")
        self.console.print("  [yellow]m[/yellow] = Modify (edit tasks)")

        try:
            answer = self.console.input("[bold]Choice (y/n/m): [/bold]")
            from cli_parsers import parse_plan_action
            return parse_plan_action(answer)
        except (EOFError, KeyboardInterrupt):
            return "reject"
