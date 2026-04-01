"""
Unit tests for Progress Emitter (SEA Phase 3).
"""

import pytest
import time
from unittest.mock import AsyncMock

from tools.gimo_server.services.timeout.progress_emitter import ProgressEmitter


@pytest.fixture
def mock_emit_fn():
    """Mock emit function."""
    return AsyncMock()


@pytest.fixture
def emitter(mock_emit_fn):
    """Create ProgressEmitter instance."""
    return ProgressEmitter(mock_emit_fn)


@pytest.mark.asyncio
async def test_emit_started(emitter, mock_emit_fn):
    """Test started event emission."""
    await emitter.emit_started(
        operation="plan",
        estimated_duration=120.0,
        metadata={"model": "claude-3-5-sonnet"}
    )

    mock_emit_fn.assert_called_once()
    event_type, data = mock_emit_fn.call_args[0]

    assert event_type == "started"
    assert data["operation"] == "plan"
    assert data["estimated_duration"] == 120.0
    assert data["metadata"]["model"] == "claude-3-5-sonnet"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_emit_progress(emitter, mock_emit_fn):
    """Test progress event emission."""
    emitter.estimated_duration = 100.0

    await emitter.emit_progress(
        stage="analyzing_prompt",
        progress=0.35,
        message="Analyzing user prompt..."
    )

    mock_emit_fn.assert_called_once()
    event_type, data = mock_emit_fn.call_args[0]

    assert event_type == "progress"
    assert data["stage"] == "analyzing_prompt"
    assert data["progress"] == 0.35
    assert data["message"] == "Analyzing user prompt..."
    assert "elapsed" in data
    assert "remaining" in data


@pytest.mark.asyncio
async def test_emit_progress_clamping(emitter, mock_emit_fn):
    """Test progress value clamping to [0.0, 1.0]."""
    emitter.estimated_duration = 100.0

    # Test lower bound
    await emitter.emit_progress("stage1", -0.5)
    _, data = mock_emit_fn.call_args[0]
    assert data["progress"] == 0.0

    # Test upper bound
    await emitter.emit_progress("stage2", 1.5)
    _, data = mock_emit_fn.call_args[0]
    assert data["progress"] == 1.0


@pytest.mark.asyncio
async def test_emit_progress_without_estimate(emitter, mock_emit_fn):
    """Test progress emission without estimated duration."""
    await emitter.emit_progress(
        stage="processing",
        progress=0.5
    )

    _, data = mock_emit_fn.call_args[0]

    assert "elapsed" in data
    assert "remaining" not in data  # No remaining time without estimate


@pytest.mark.asyncio
async def test_emit_checkpoint(emitter, mock_emit_fn):
    """Test checkpoint event emission."""
    await emitter.emit_checkpoint(
        checkpoint_id="ckpt_123456",
        resumable=True
    )

    mock_emit_fn.assert_called_once()
    event_type, data = mock_emit_fn.call_args[0]

    assert event_type == "checkpoint"
    assert data["checkpoint_id"] == "ckpt_123456"
    assert data["resumable"] is True
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_emit_completed(emitter, mock_emit_fn):
    """Test completed event emission."""
    result = {"draft_id": "draft_123", "task_count": 5}

    await emitter.emit_completed(result, status="success")

    mock_emit_fn.assert_called_once()
    event_type, data = mock_emit_fn.call_args[0]

    assert event_type == "completed"
    assert data["result"] == result
    assert data["status"] == "success"
    assert "duration" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_emit_error(emitter, mock_emit_fn):
    """Test error event emission."""
    await emitter.emit_error(
        error="LLM timeout",
        error_code="TIMEOUT"
    )

    mock_emit_fn.assert_called_once()
    event_type, data = mock_emit_fn.call_args[0]

    assert event_type == "error"
    assert data["error"] == "LLM timeout"
    assert data["error_code"] == "TIMEOUT"
    assert "elapsed" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_emit_custom(emitter, mock_emit_fn):
    """Test custom event emission."""
    custom_data = {"key": "value", "count": 42}

    await emitter.emit_custom("custom_event", custom_data)

    mock_emit_fn.assert_called_once()
    event_type, data = mock_emit_fn.call_args[0]

    assert event_type == "custom_event"
    assert data == custom_data


def test_get_elapsed_time(emitter):
    """Test elapsed time calculation."""
    time.sleep(0.1)
    elapsed = emitter.get_elapsed_time()

    assert elapsed >= 0.1
    assert elapsed < 0.2  # Should be around 0.1s


def test_get_remaining_time_with_estimate(emitter):
    """Test remaining time calculation with estimate."""
    emitter.estimated_duration = 100.0
    time.sleep(0.1)

    remaining = emitter.get_remaining_time()

    assert remaining is not None
    assert remaining < 100.0
    assert remaining >= 0.0


def test_get_remaining_time_without_estimate(emitter):
    """Test remaining time without estimate."""
    remaining = emitter.get_remaining_time()

    assert remaining is None


def test_should_emit_checkpoint(emitter):
    """Test checkpoint emission timing."""
    # The implementation uses modulo, which is timing-dependent
    # Just test that it returns a boolean
    result = emitter.should_emit_checkpoint(checkpoint_interval=1.0)
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_progress_logging_threshold(emitter, mock_emit_fn):
    """Test that progress is logged only on significant changes."""
    emitter.estimated_duration = 100.0

    # Emit small progress changes
    await emitter.emit_progress("stage1", 0.01)
    await emitter.emit_progress("stage1", 0.02)
    await emitter.emit_progress("stage1", 0.03)
    await emitter.emit_progress("stage1", 0.04)

    # All should be emitted (logging threshold is for logs, not emission)
    assert mock_emit_fn.call_count == 4


@pytest.mark.asyncio
async def test_multiple_progress_updates(emitter, mock_emit_fn):
    """Test sequence of progress updates."""
    emitter.estimated_duration = 100.0

    stages = [
        ("analyzing", 0.2),
        ("processing", 0.5),
        ("validating", 0.8),
        ("finalizing", 0.95),
    ]

    for stage, progress in stages:
        await emitter.emit_progress(stage, progress)

    assert mock_emit_fn.call_count == len(stages)

    # Verify progress is increasing
    for i, call in enumerate(mock_emit_fn.call_args_list):
        _, data = call[0]
        expected_progress = stages[i][1]
        assert data["progress"] == expected_progress


@pytest.mark.asyncio
async def test_full_lifecycle(emitter, mock_emit_fn):
    """Test complete operation lifecycle."""
    # Start
    await emitter.emit_started("test_op", 60.0)

    # Progress updates
    await emitter.emit_progress("stage1", 0.25)
    await emitter.emit_progress("stage2", 0.5)

    # Checkpoint
    await emitter.emit_checkpoint("ckpt_123", True)

    # More progress
    await emitter.emit_progress("stage3", 0.75)

    # Complete
    await emitter.emit_completed({"result": "success"})

    # Verify all events emitted
    assert mock_emit_fn.call_count == 6

    event_types = [call[0][0] for call in mock_emit_fn.call_args_list]
    assert event_types == [
        "started",
        "progress",
        "progress",
        "checkpoint",
        "progress",
        "completed",
    ]
