"""Routing snapshot persistence parity (R20-006).

Asserts that the prompt-based ``LlmExecute`` stage projects the resolved
provider/model binding back onto the OpsRun via
``OpsService.merge_run_meta(routing_snapshot=...)``. Before R20-006,
``routing_snapshot`` was only written by ``spawn_via_draft``, leaving
prompt-only runs (CLI/MCP/chat) with a null snapshot — the gap that this
test guards.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.gimo_server.engine.contracts import StageInput
from tools.gimo_server.engine.stages.llm_execute import LlmExecute


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.llm_execute.OpsService")
@patch("tools.gimo_server.engine.stages.llm_execute.StorageService")
@patch("tools.gimo_server.engine.stages.llm_execute.ObservabilityService")
@patch("tools.gimo_server.engine.stages.llm_execute.ProviderService")
async def test_routing_snapshot_persisted_after_llm_execute(
    mock_provider, mock_obs, mock_storage_cls, mock_ops
):
    mock_provider.static_generate = AsyncMock(return_value={
        "provider": "openai",
        "model": "gpt-4o",
        "content": "ok",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "tokens_used": 15,
        "cost_usd": 0.0123,
    })
    mock_provider.get_config.return_value = MagicMock(
        providers={"openai": MagicMock(provider_type="openai", type="openai", auth_mode="api_key")}
    )
    mock_storage_cls.return_value = MagicMock(cost=MagicMock())

    stage = LlmExecute()
    inp = StageInput(
        run_id="run-r20-006",
        context={
            "prompt": "say hi",
            "execution_policy_name": "workspace_safe",
        },
    )

    result = await stage.execute(inp)
    assert result.status == "continue"

    # Find the merge_run_meta call that carries routing_snapshot.
    snap_calls = [
        c for c in mock_ops.merge_run_meta.call_args_list
        if "routing_snapshot" in c.kwargs
    ]
    assert snap_calls, (
        "LlmExecute did not project routing_snapshot via merge_run_meta "
        "(R20-006 regression)"
    )
    snap = snap_calls[-1].kwargs["routing_snapshot"]
    assert snap["provider"] == "openai"
    assert snap["model"] == "gpt-4o"
    assert snap["resolved_by"] == "llm_execute"
    assert snap["execution_policy"] == "workspace_safe"
    assert snap["tokens_used"] == 15
    assert pytest.approx(snap["cost_usd"], rel=1e-6) == 0.0123
    # run_id positional must be the live run, not the draft.
    assert snap_calls[-1].args[0] == "run-r20-006"
