"""Tests for LlmExecute stage."""
from __future__ import annotations
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from tools.gimo_server.engine.contracts import StageInput, StageOutput
from tools.gimo_server.engine.stages.llm_execute import LlmExecute


@pytest.fixture
def stage():
    return LlmExecute()


def _make_input(prompt: str = "Write hello world", multi_pass: bool = False, max_passes: int = 3) -> StageInput:
    ctx = {"prompt": prompt, "gen_context": {"lang": "python"}}
    if multi_pass:
        ctx["ace_multi_pass"] = True
        ctx["ace_max_passes"] = max_passes
    return StageInput(run_id="run-llm-001", context=ctx)


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.llm_execute.ProviderService")
async def test_happy_path(mock_provider, stage):
    mock_provider.static_generate = AsyncMock(return_value={
        "content": "print('hello')",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost_usd": 0.001,
    })

    result = await stage.execute(_make_input())
    assert result.status == "continue"
    assert result.artifacts["content"] == "print('hello')"
    assert result.artifacts["usage"]["prompt_tokens"] == 10


@pytest.mark.asyncio
async def test_missing_prompt_fails(stage):
    inp = StageInput(run_id="run-llm-002", context={})
    result = await stage.execute(inp)
    assert result.status == "fail"
    assert "Missing prompt" in result.artifacts.get("error", "")


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.llm_execute.ProviderService")
async def test_provider_exception_fails(mock_provider, stage):
    mock_provider.static_generate = AsyncMock(side_effect=Exception("API down"))

    result = await stage.execute(_make_input())
    assert result.status == "fail"
    assert "API down" in result.artifacts.get("error", "")


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.llm_execute.ProviderService")
async def test_multi_pass_with_critic_approval(mock_provider, stage):
    mock_provider.static_generate = AsyncMock(return_value={
        "content": "good code",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost_usd": 0.001,
    })

    critic_verdict = MagicMock()
    critic_verdict.approved = True

    with patch("tools.gimo_server.services.critic_service.CriticService.evaluate", new_callable=AsyncMock, return_value=critic_verdict):
        result = await stage.execute(_make_input(multi_pass=True, max_passes=3))

    assert result.status == "continue"
    # Should have called generate only once since critic approved on first pass
    assert mock_provider.static_generate.call_count == 1


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.llm_execute.ProviderService")
async def test_multi_pass_retries_on_critic_rejection(mock_provider, stage):
    mock_provider.static_generate = AsyncMock(return_value={
        "content": "improved code",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost_usd": 0.001,
    })

    reject_verdict = MagicMock()
    reject_verdict.approved = False
    reject_verdict.severity = "medium"
    reject_verdict.issues = ["missing type hints"]

    with patch("tools.gimo_server.services.critic_service.CriticService.evaluate", new_callable=AsyncMock, return_value=reject_verdict):
        result = await stage.execute(_make_input(multi_pass=True, max_passes=2))

    assert result.status == "continue"
    assert mock_provider.static_generate.call_count == 2


@pytest.mark.asyncio
async def test_rollback_is_noop(stage):
    await stage.rollback(_make_input())  # Should not raise
