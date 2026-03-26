from typing import Any, Callable, Optional
from dataclasses import dataclass
import time

@dataclass
class Notice:
    level: str  # "info", "warning", "error"
    message: str
    created_at: float
    ttl_seconds: Optional[int]
    sticky: bool

class SlashCommand:
    def __init__(self, name: str, help_text: str, usage: str, aliases: tuple[str, ...] = ()):
        self.name = name
        self.help_text = help_text
        self.usage = usage
        self.aliases = aliases

COMMAND_REGISTRY: list[SlashCommand] = [
    SlashCommand("/help", "Show chat commands", "/help"),
    SlashCommand("/provider", "Show active provider/model, or switch provider", "/provider [id] [model]", aliases=("/providers",)),
    SlashCommand("/models", "List models exposed by the active provider", "/models"),
    SlashCommand("/model", "Show preferred model from local config, or set it", "/model [id]"),
    SlashCommand("/workspace", "Show current workspace path", "/workspace"),
    SlashCommand("/thread", "Show current thread id", "/thread"),
    SlashCommand("/workers", "Show the available pool of AI workers", "/workers", aliases=("/pool",)),
    SlashCommand("/status", "Run chat preflight summary (telemetry and limits)", "/status"),
    # ── P0: New commands ──────────────────────────────────────────────────────
    SlashCommand("/undo", "Safe undo: git revert --no-edit HEAD (assumes last commit is AI)", "/undo"),
    SlashCommand("/clear", "Clear local chat view (does not touch thread or backend context)", "/clear"),
    SlashCommand("/reset", "Reset backend thread context (prompts y/N confirmation)", "/reset"),
    SlashCommand("/tokens", "Show token usage: input, output, cost, ctx window %, breakdown", "/tokens"),
    SlashCommand("/diff", "Show current diff from backend (/ops/files/diff)", "/diff"),
    SlashCommand("/effort", "Set orchestrator effort level: low | high | max", "/effort <low|high|max>"),
    SlashCommand("/permissions", "Change HITL mode live: suggest | auto-edit | full-auto", "/permissions <suggest|auto-edit|full-auto>"),
    SlashCommand("/add", "Add a file to the active thread context", "/add <path>"),
    SlashCommand("/debug", "Toggle debug/verbose mode for current session", "/debug"),
    SlashCommand("/merge", "Finalize manual merge for a run in AWAITING_MERGE status", "/merge [run_id]"),
    # ── Session control ───────────────────────────────────────────────────────
    SlashCommand("/exit", "End the session", "/exit", aliases=("/quit",)),
]

EFFORT_VALUES: frozenset[str] = frozenset({"low", "high", "max"})
PERMISSION_VALUES: frozenset[str] = frozenset({"suggest", "auto-edit", "full-auto"})


def get_autocomplete_dict() -> dict[str, str]:
    """Return a dict of command -> help text for prompt_toolkit completer."""
    res = {}
    for cmd in COMMAND_REGISTRY:
        res[cmd.name] = cmd.help_text
        for alias in cmd.aliases:
            res[alias] = cmd.help_text
    return res


def get_help_text() -> str:
    """Format the help text for all registered commands."""
    lines = []
    for cmd in COMMAND_REGISTRY:
        lines.append(f"{cmd.usage:<35} {cmd.help_text}")
    return "\n".join(lines)


def dispatch_slash_command(
    command_str: str,
    arg_str: str,
    callbacks: dict[str, Callable[..., Any]],
) -> tuple[bool, Any]:
    """
    Dispatch a slash command. Returns (handled, result_payload).
    Uses dependency injection dict 'callbacks' to execute actual logic without circular imports.
    """
    cmd_name = command_str.lower()

    for cmd in COMMAND_REGISTRY:
        if cmd_name == cmd.name or cmd_name in cmd.aliases:
            # ── Session control ──────────────────────────────────────────────
            if cmd_name in {"/exit", "/quit"}:
                return True, callbacks["exit_session"]()

            # ── Informational ────────────────────────────────────────────────
            if cmd_name == "/help":
                return True, callbacks["show_help"]()
            if cmd_name == "/workspace":
                return True, callbacks["show_workspace"]()
            if cmd_name == "/thread":
                return True, callbacks["show_thread"]()
            if cmd_name in {"/provider", "/providers"}:
                return True, callbacks["handle_provider"](arg_str)
            if cmd_name == "/model":
                return True, callbacks["handle_model"](arg_str)
            if cmd_name == "/models":
                return True, callbacks["list_models"]()
            if cmd_name in {"/workers", "/pool"}:
                return True, callbacks["show_workers"]()
            if cmd_name == "/status":
                return True, callbacks["show_status"]()

            # ── P0: New commands ─────────────────────────────────────────────
            if cmd_name == "/undo":
                return True, callbacks["undo"]()

            if cmd_name == "/clear":
                return True, callbacks["clear_view"]()

            if cmd_name == "/reset":
                return True, callbacks["reset_context"]()

            if cmd_name == "/tokens":
                return True, callbacks["show_tokens"]()

            if cmd_name == "/diff":
                return True, callbacks["show_diff"]()

            if cmd_name == "/effort":
                effort_val = arg_str.strip().lower()
                if effort_val not in EFFORT_VALUES:
                    return True, callbacks["invalid_arg"](
                        f"/effort requires one of: low, high, max — got: '{effort_val}'"
                    )
                return True, callbacks["set_effort"](effort_val)

            if cmd_name == "/permissions":
                perm_val = arg_str.strip().lower()
                if perm_val not in PERMISSION_VALUES:
                    return True, callbacks["invalid_arg"](
                        f"/permissions requires one of: suggest, auto-edit, full-auto — got: '{perm_val}'"
                    )
                return True, callbacks["set_permissions"](perm_val)

            if cmd_name == "/add":
                path_val = arg_str.strip()
                if not path_val:
                    return True, callbacks["invalid_arg"]("/add requires a file path argument")
                return True, callbacks["add_file"](path_val)

            if cmd_name == "/debug":
                return True, callbacks["toggle_debug"]()

            if cmd_name == "/merge":
                return True, callbacks["merge_run"](arg_str)

            # Fallthrough for registered but unhandled commands
            callbacks["unknown_command"](cmd_name)
            return True, None

    callbacks["unknown_command"](cmd_name)
    return True, None
