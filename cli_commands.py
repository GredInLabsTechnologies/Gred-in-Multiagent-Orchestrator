from typing import Any, Callable

class SlashCommand:
    def __init__(self, name: str, help_text: str, usage: str, aliases: tuple[str, ...] = ()):
        self.name = name
        self.help_text = help_text
        self.usage = usage
        self.aliases = aliases

COMMAND_REGISTRY: list[SlashCommand] = [
    SlashCommand("/help", "Show chat commands", "/help"),
    SlashCommand("/provider", "Show active provider and agent/model, or switch provider", "/provider [id] [model]", aliases=("/providers",)),
    SlashCommand("/models", "List models exposed by the active provider", "/models"),
    SlashCommand("/model", "Show preferred model from local config, or set it", "/model [id]"),
    SlashCommand("/workspace", "Show current workspace path", "/workspace"),
    SlashCommand("/thread", "Show current thread id", "/thread"),
    SlashCommand("/workers", "Show the available pool of AI workers", "/workers", aliases=("/pool",)),
    SlashCommand("/status", "Run chat preflight summary (telemetry and limits)", "/status"),
    SlashCommand("/exit", "End the session", "/exit", aliases=("/quit",)),
]

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
        lines.append(f"{cmd.usage:<25} {cmd.help_text}")
    return "\n".join(lines)

def dispatch_slash_command(
    command_str: str,
    arg_str: str,
    callbacks: dict[str, Callable[..., Any]]
) -> tuple[bool, Any]:
    """
    Dispatch a slash command. Returns (handled, result_payload).
    Uses dependency injection dict 'callbacks' to execute actual logic without circular imports.
    """
    cmd_name = command_str.lower()
    for cmd in COMMAND_REGISTRY:
        if cmd_name == cmd.name or cmd_name in cmd.aliases:
            if cmd_name in {"/exit", "/quit"}:
                return True, callbacks["exit_session"]()
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
                
    callbacks["unknown_command"](cmd_name)
    return True, None
