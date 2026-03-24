CODE_EDITING_TOOL_NAMES = frozenset({
    "write_file",
    "search_replace",
    "patch_file",
})

def get_budget_color(rem_pct: float | None) -> str:
    """Return 'green', 'yellow', or 'red' based on remaining budget percentage."""
    if rem_pct is None:
        return "green"
    if rem_pct < 20:
        return "red"
    if rem_pct < 50:
        return "yellow"
    return "green"
