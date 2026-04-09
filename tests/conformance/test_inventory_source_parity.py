"""Inventory source filtering parity (R20-007).

Asserts that ``SubAgentManager.get_sub_agents`` honours the
``source`` discriminator and ``exclude_orphans`` flag added in R20-007.
This guards the schema-level fix that lets UI/MCP callers tell apart
auto-discovered local models from governed spawn projections, and
prevents orphan spawn records (failed readiness, no runId) from
contaminating either view.
"""
from __future__ import annotations

import pytest

from tools.gimo_server.models.sub_agent import SubAgent, SubAgentConfig
from tools.gimo_server.services.sub_agent_manager import SubAgentManager


@pytest.fixture
def _isolated_inventory():
    """Snapshot and restore the in-memory sub-agent registry."""
    snapshot = dict(SubAgentManager._sub_agents)
    SubAgentManager._sub_agents.clear()
    try:
        yield
    finally:
        SubAgentManager._sub_agents.clear()
        SubAgentManager._sub_agents.update(snapshot)


def _mk(id_: str, *, source: str, run_id: str | None) -> SubAgent:
    return SubAgent(
        id=id_,
        parentId="parent-r20-007",
        name=id_,
        model="qwen2.5-coder:3b",
        status="idle",
        config=SubAgentConfig(),
        source=source,  # type: ignore[arg-type]
        runId=run_id,
    )


def test_get_sub_agents_filters_by_source(_isolated_inventory):
    SubAgentManager._sub_agents["auto-1"] = _mk("auto-1", source="auto_discovery", run_id=None)
    SubAgentManager._sub_agents["spawn-ok"] = _mk("spawn-ok", source="spawn", run_id="run-1")
    SubAgentManager._sub_agents["spawn-orphan"] = _mk("spawn-orphan", source="spawn", run_id=None)

    auto = SubAgentManager.get_sub_agents(source="auto_discovery")
    spawn = SubAgentManager.get_sub_agents(source="spawn")

    assert {a.id for a in auto} == {"auto-1"}
    assert {a.id for a in spawn} == {"spawn-ok", "spawn-orphan"}


def test_get_sub_agents_exclude_orphans(_isolated_inventory):
    SubAgentManager._sub_agents["auto-1"] = _mk("auto-1", source="auto_discovery", run_id=None)
    SubAgentManager._sub_agents["spawn-ok"] = _mk("spawn-ok", source="spawn", run_id="run-1")
    SubAgentManager._sub_agents["spawn-orphan"] = _mk("spawn-orphan", source="spawn", run_id=None)

    kept = SubAgentManager.get_sub_agents(exclude_orphans=True)
    ids = {a.id for a in kept}
    # auto_discovery is always kept; spawn requires runId
    assert "auto-1" in ids
    assert "spawn-ok" in ids
    assert "spawn-orphan" not in ids
