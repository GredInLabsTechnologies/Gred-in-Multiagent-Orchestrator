from __future__ import annotations

from tools.gimo_server.mcp_bridge import registrar


class _DummyMcp:
    def __init__(self) -> None:
        self.tools: list[str] = []

    def add_tool(self, func) -> None:
        self.tools.append(func.__name__)


def test_phase1_mcp_alias_tools_are_registered():
    dummy = _DummyMcp()

    registrar.register_all(dummy)

    tool_names = set(dummy.tools)
    assert "plan_create" in tool_names
    assert "plan_execute" in tool_names
    assert "cost_estimate" in tool_names
