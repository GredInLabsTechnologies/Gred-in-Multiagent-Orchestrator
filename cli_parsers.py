def parse_yes_no(text: str) -> bool:
    """Evaluate if the user input means Yes/Approve."""
    if not text:
        return False
    return text.strip().lower() in {"y", "yes", "si", "sí", "approve"}

def parse_plan_action(text: str) -> str:
    """Evaluate plan approval input. Returns 'approve', 'modify', or 'reject'."""
    if not text:
        return "reject"
    val = text.strip().lower()
    if val in {"y", "yes", "si", "sí", "approve"}:
        return "approve"
    if val in {"m", "modify", "edit"}:
        return "modify"
    return "reject"

def is_terminal_status(status: str, active_statuses: frozenset, terminal_statuses: frozenset) -> bool:
    """Determine if a run status is terminal."""
    return status in terminal_statuses or (bool(status) and status not in active_statuses)
