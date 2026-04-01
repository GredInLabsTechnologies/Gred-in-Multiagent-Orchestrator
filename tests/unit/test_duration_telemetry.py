"""
Unit tests for Duration Telemetry Service (GAEP Phase 1).
"""

import time
from unittest.mock import MagicMock, patch
import pytest

from tools.gimo_server.services.timeout.duration_telemetry_service import DurationTelemetryService


@pytest.fixture
def mock_gics():
    """Mock GICS service for testing."""
    gics = MagicMock()
    gics.put = MagicMock(return_value=True)
    gics.get = MagicMock(return_value=None)
    gics.scan = MagicMock(return_value=[])
    return gics


@pytest.fixture(autouse=True)
def reset_gics():
    """Reset GICS instance before each test."""
    DurationTelemetryService._gics = None
    yield
    DurationTelemetryService._gics = None


def test_record_operation_duration_success(mock_gics):
    """Test successful recording of operation duration."""
    DurationTelemetryService.set_gics(mock_gics)

    key = DurationTelemetryService.record_operation_duration(
        operation="plan",
        duration=42.5,
        context={
            "model": "claude-3-5-sonnet",
            "prompt_length": 150,
            "provider": "anthropic",
        },
        success=True
    )

    # Verify GICS.put was called
    assert mock_gics.put.called
    call_args = mock_gics.put.call_args

    # Check key format
    stored_key = call_args[0][0]
    assert stored_key.startswith("ops:duration:plan:")
    assert key == stored_key

    # Check fields
    fields = call_args[0][1]
    assert fields["operation"] == "plan"
    assert fields["duration_s"] == 42.5
    assert fields["success"] is True
    assert fields["context"]["model"] == "claude-3-5-sonnet"
    assert fields["context"]["prompt_length"] == 150
    assert "timestamp" in fields


def test_record_operation_duration_failure(mock_gics):
    """Test recording of failed operation."""
    DurationTelemetryService.set_gics(mock_gics)

    key = DurationTelemetryService.record_operation_duration(
        operation="run",
        duration=10.2,
        context={"model": "gpt-4"},
        success=False
    )

    # Verify stored with success=False
    fields = mock_gics.put.call_args[0][1]
    assert fields["success"] is False
    assert key is not None


def test_get_historical_durations_empty(mock_gics):
    """Test retrieval when no historical data exists."""
    DurationTelemetryService.set_gics(mock_gics)
    mock_gics.scan.return_value = []

    durations = DurationTelemetryService.get_historical_durations(
        operation="plan",
        limit=100
    )

    assert durations == []
    mock_gics.scan.assert_called_once()


def test_get_historical_durations_with_data(mock_gics):
    """Test retrieval of historical durations."""
    DurationTelemetryService.set_gics(mock_gics)

    # Mock historical records
    mock_gics.scan.return_value = [
        {
            "key": "ops:duration:plan:1000",
            "fields": {
                "operation": "plan",
                "duration_s": 45.2,
                "success": True,
                "context": {"model": "claude-3-5-sonnet"}
            }
        },
        {
            "key": "ops:duration:plan:2000",
            "fields": {
                "operation": "plan",
                "duration_s": 38.7,
                "success": True,
                "context": {"model": "claude-3-5-sonnet"}
            }
        },
        {
            "key": "ops:duration:plan:3000",
            "fields": {
                "operation": "plan",
                "duration_s": 52.1,
                "success": False,  # Should be filtered out
                "context": {"model": "claude-3-5-sonnet"}
            }
        },
    ]

    durations = DurationTelemetryService.get_historical_durations(
        operation="plan",
        limit=100
    )

    # Should only include successful operations
    assert len(durations) == 2
    assert 45.2 in durations
    assert 38.7 in durations
    assert 52.1 not in durations  # Failed operation excluded


def test_context_similarity_matching():
    """Test context similarity filter."""
    target = {
        "model": "claude-3-5-sonnet",
        "provider": "anthropic",
        "prompt_length": 100,
    }

    # Exact match
    candidate_exact = {
        "model": "claude-3-5-sonnet",
        "provider": "anthropic",
        "prompt_length": 105,
    }
    assert DurationTelemetryService._is_similar_context(target, candidate_exact)

    # Different model (should not match)
    candidate_different_model = {
        "model": "gpt-4",
        "provider": "openai",
        "prompt_length": 100,
    }
    assert not DurationTelemetryService._is_similar_context(target, candidate_different_model)

    # Too different prompt length (>2x, should not match)
    candidate_long_prompt = {
        "model": "claude-3-5-sonnet",
        "provider": "anthropic",
        "prompt_length": 300,  # 3x larger
    }
    assert not DurationTelemetryService._is_similar_context(target, candidate_long_prompt)

    # Similar prompt length (within 2x, should match)
    candidate_similar = {
        "model": "claude-3-5-sonnet",
        "provider": "anthropic",
        "prompt_length": 150,  # 1.5x larger
    }
    assert DurationTelemetryService._is_similar_context(target, candidate_similar)


def test_get_stats_for_operation(mock_gics):
    """Test aggregated statistics calculation."""
    DurationTelemetryService.set_gics(mock_gics)

    # Mock historical records
    mock_gics.scan.return_value = [
        {"key": "ops:duration:plan:1", "fields": {"success": True, "duration_s": 10.0}},
        {"key": "ops:duration:plan:2", "fields": {"success": True, "duration_s": 20.0}},
        {"key": "ops:duration:plan:3", "fields": {"success": True, "duration_s": 30.0}},
        {"key": "ops:duration:plan:4", "fields": {"success": True, "duration_s": 40.0}},
        {"key": "ops:duration:plan:5", "fields": {"success": True, "duration_s": 50.0}},
        {"key": "ops:duration:plan:6", "fields": {"success": False, "duration_s": 5.0}},
    ]

    stats = DurationTelemetryService.get_stats_for_operation("plan")

    assert stats["operation"] == "plan"
    assert stats["total_samples"] == 6
    assert stats["success_rate"] == pytest.approx(5/6, rel=0.01)  # 5 successes out of 6
    assert stats["avg_duration_s"] == pytest.approx(25.8, rel=0.1)  # (10+20+30+40+50+5)/6
    assert stats["p50_duration_s"] > 0
    assert stats["p95_duration_s"] > 0
    assert stats["max_duration_s"] == 50.0


def test_get_stats_empty(mock_gics):
    """Test stats calculation with no data."""
    DurationTelemetryService.set_gics(mock_gics)
    mock_gics.scan.return_value = []

    stats = DurationTelemetryService.get_stats_for_operation("plan")

    assert stats["operation"] == "plan"
    assert stats["total_samples"] == 0
    assert stats["success_rate"] == 0.0
    assert stats["avg_duration_s"] == 0.0


def test_gics_not_initialized():
    """Test that operations fail gracefully when GICS not initialized."""
    # Don't set GICS - should return None instead of raising
    key = DurationTelemetryService.record_operation_duration(
        operation="plan",
        duration=10.0,
        context={},
        success=True
    )

    # Should return None when GICS not available
    assert key is None


def test_record_with_gics_failure(mock_gics):
    """Test graceful handling of GICS failures."""
    DurationTelemetryService.set_gics(mock_gics)
    mock_gics.put.side_effect = Exception("GICS down")

    # Should not raise, but should return None
    key = DurationTelemetryService.record_operation_duration(
        operation="plan",
        duration=10.0,
        context={},
        success=True
    )

    assert key is None


def test_historical_durations_with_context_filter(mock_gics):
    """Test context-based filtering of historical durations."""
    DurationTelemetryService.set_gics(mock_gics)

    mock_gics.scan.return_value = [
        {
            "key": "ops:duration:plan:1",
            "fields": {
                "duration_s": 45.0,
                "success": True,
                "context": {"model": "claude-3-5-sonnet", "prompt_length": 100}
            }
        },
        {
            "key": "ops:duration:plan:2",
            "fields": {
                "duration_s": 10.0,
                "success": True,
                "context": {"model": "gpt-4", "prompt_length": 100}  # Different model
            }
        },
        {
            "key": "ops:duration:plan:3",
            "fields": {
                "duration_s": 50.0,
                "success": True,
                "context": {"model": "claude-3-5-sonnet", "prompt_length": 120}
            }
        },
    ]

    # Filter by similar context
    durations = DurationTelemetryService.get_historical_durations(
        operation="plan",
        context={"model": "claude-3-5-sonnet", "prompt_length": 100},
        limit=100
    )

    # Should only include claude-3-5-sonnet with similar prompt length
    assert len(durations) == 2
    assert 45.0 in durations
    assert 50.0 in durations
    assert 10.0 not in durations  # Different model filtered out
