"""Tests for GitPipeline stage."""
from __future__ import annotations
import pytest
from unittest.mock import patch, AsyncMock

from tools.gimo_server.engine.contracts import StageInput, StageOutput
from tools.gimo_server.engine.stages.git_pipeline import GitPipeline


@pytest.fixture
def stage():
    return GitPipeline()


def _make_input(run_id: str = "run-git-001") -> StageInput:
    return StageInput(run_id=run_id, context={})


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.git_pipeline.MergeGateService")
async def test_happy_path_handled(mock_merge, stage):
    mock_merge.execute_run = AsyncMock(return_value=True)

    result = await stage.execute(_make_input())
    assert result.status == "continue"
    assert result.artifacts["git_pipeline_result"]["handled"] is True
    mock_merge.execute_run.assert_awaited_once_with("run-git-001")


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.git_pipeline.MergeGateService")
async def test_not_handled_fails(mock_merge, stage):
    mock_merge.execute_run = AsyncMock(return_value=False)

    result = await stage.execute(_make_input())
    assert result.status == "fail"
    assert result.artifacts["git_pipeline_result"]["handled"] is False


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.git_pipeline.MergeGateService")
async def test_none_return_fails(mock_merge, stage):
    mock_merge.execute_run = AsyncMock(return_value=None)

    result = await stage.execute(_make_input())
    assert result.status == "fail"


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.git_pipeline.MergeGateService")
async def test_exception_fails(mock_merge, stage):
    mock_merge.execute_run = AsyncMock(side_effect=RuntimeError("git conflict"))

    result = await stage.execute(_make_input())
    assert result.status == "fail"
    assert "git conflict" in result.artifacts.get("error", "")


@pytest.mark.asyncio
@patch("tools.gimo_server.engine.stages.git_pipeline.MergeGateService")
async def test_passes_correct_run_id(mock_merge, stage):
    mock_merge.execute_run = AsyncMock(return_value=True)

    await stage.execute(_make_input(run_id="custom-run-42"))
    mock_merge.execute_run.assert_awaited_once_with("custom-run-42")


@pytest.mark.asyncio
async def test_rollback_is_noop(stage):
    await stage.rollback(_make_input())  # Should not raise
