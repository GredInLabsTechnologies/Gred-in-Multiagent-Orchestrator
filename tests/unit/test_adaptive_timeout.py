"""
Unit tests for Adaptive Timeout Service (GAEP Phase 2).
"""

from unittest.mock import patch
import pytest

from tools.gimo_server.services.timeout.adaptive_timeout_service import AdaptiveTimeoutService


PATCH_PATH = "tools.gimo_server.services.timeout.duration_telemetry_service.DurationTelemetryService.get_historical_durations"


@pytest.fixture(autouse=True)
def reset_gics():
    """Reset GICS instance before each test."""
    AdaptiveTimeoutService._gics = None
    yield
    AdaptiveTimeoutService._gics = None


@pytest.fixture
def mock_durations():
    """Mock historical durations (10, 20, ..., 100 seconds)."""
    return [float(i * 10) for i in range(1, 11)]


def test_predict_timeout_no_history():
    """Test prediction falls back to default when no history."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = []

        timeout = AdaptiveTimeoutService.predict_timeout("plan")

        # Should return default
        assert timeout == AdaptiveTimeoutService.DEFAULT_TIMEOUTS["plan"]


def test_predict_timeout_insufficient_samples():
    """Test prediction falls back to default with < 5 samples."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = [10.0, 20.0, 30.0]

        timeout = AdaptiveTimeoutService.predict_timeout("plan")

        # Should return default (insufficient data)
        assert timeout == AdaptiveTimeoutService.DEFAULT_TIMEOUTS["plan"]


def test_predict_timeout_with_history(mock_durations):
    """Test prediction with sufficient historical data."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = mock_durations

        timeout = AdaptiveTimeoutService.predict_timeout("plan")

        # P95 of [10, 20, ..., 100] is ~95
        # With 20% safety margin: 95 * 1.2 = 114
        assert 100 < timeout < 150  # Reasonable range


def test_predict_timeout_model_adjustment(mock_durations):
    """Test model-based timeout adjustment."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = mock_durations

        # Opus model should get +50% adjustment
        timeout_opus = AdaptiveTimeoutService.predict_timeout(
            "plan",
            context={"model": "claude-opus-4"}
        )

        # Haiku model should get -20% adjustment
        timeout_haiku = AdaptiveTimeoutService.predict_timeout(
            "plan",
            context={"model": "claude-haiku-3-5"}
        )

        # Opus should be significantly longer than haiku
        assert timeout_opus > timeout_haiku * 1.3


def test_predict_timeout_system_load_adjustment(mock_durations):
    """Test system load-based timeout adjustment."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = mock_durations

        timeout_low = AdaptiveTimeoutService.predict_timeout(
            "plan",
            context={"system_load": "low"}
        )

        timeout_high = AdaptiveTimeoutService.predict_timeout(
            "plan",
            context={"system_load": "high"}
        )

        # High load should get longer timeout
        assert timeout_high > timeout_low


def test_predict_timeout_complexity_adjustment(mock_durations):
    """Test complexity-based adjustment for plan operations."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = mock_durations

        timeout_simple = AdaptiveTimeoutService.predict_timeout(
            "plan",
            context={"complexity": "simple"}
        )

        timeout_complex = AdaptiveTimeoutService.predict_timeout(
            "plan",
            context={"complexity": "complex"}
        )

        # Complex should get longer timeout
        assert timeout_complex > timeout_simple * 1.5


def test_predict_timeout_prompt_length_adjustment(mock_durations):
    """Test prompt length adjustment for plan operations."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = mock_durations

        timeout_short = AdaptiveTimeoutService.predict_timeout(
            "plan",
            context={"prompt_length": 100}
        )

        timeout_long = AdaptiveTimeoutService.predict_timeout(
            "plan",
            context={"prompt_length": 2000}
        )

        # Long prompt should get longer timeout
        assert timeout_long > timeout_short


def test_predict_timeout_file_count_adjustment(mock_durations):
    """Test file count adjustment for run operations."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = mock_durations

        timeout_few = AdaptiveTimeoutService.predict_timeout(
            "run",
            context={"file_count": 3}
        )

        timeout_many = AdaptiveTimeoutService.predict_timeout(
            "run",
            context={"file_count": 15}
        )

        # Many files should get longer timeout
        assert timeout_many > timeout_few


def test_predict_timeout_bounds_enforcement(mock_durations):
    """Test that predicted timeouts respect MIN/MAX bounds."""
    with patch(PATCH_PATH) as mock_get:
        # Very long historical durations
        mock_get.return_value = [1000.0] * 10

        timeout = AdaptiveTimeoutService.predict_timeout("plan")

        # Should be capped at MAX_TIMEOUT
        assert timeout <= AdaptiveTimeoutService.MAX_TIMEOUT

        # Very short historical durations
        mock_get.return_value = [1.0] * 10

        timeout = AdaptiveTimeoutService.predict_timeout("plan")

        # Should be at least MIN_TIMEOUT
        assert timeout >= AdaptiveTimeoutService.MIN_TIMEOUT


def test_predict_timeout_simple():
    """Test simplified prediction without context."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = []

        timeout = AdaptiveTimeoutService.predict_timeout_simple("plan")

        assert timeout == AdaptiveTimeoutService.DEFAULT_TIMEOUTS["plan"]


def test_get_confidence_level():
    """Test confidence level calculation based on sample count."""
    with patch(PATCH_PATH) as mock_get:
        # High confidence (>50 samples)
        mock_get.return_value = [10.0] * 60
        confidence = AdaptiveTimeoutService.get_confidence_level("plan")
        assert confidence == "high"

        # Medium confidence (10-50 samples)
        mock_get.return_value = [10.0] * 25
        confidence = AdaptiveTimeoutService.get_confidence_level("plan")
        assert confidence == "medium"

        # Low confidence (<10 samples)
        mock_get.return_value = [10.0] * 5
        confidence = AdaptiveTimeoutService.get_confidence_level("plan")
        assert confidence == "low"

        # No samples
        mock_get.return_value = []
        confidence = AdaptiveTimeoutService.get_confidence_level("plan")
        assert confidence == "low"


def test_recommend_timeout_with_metadata(mock_durations):
    """Test timeout recommendation with metadata."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = mock_durations

        result = AdaptiveTimeoutService.recommend_timeout_with_metadata("plan")

        assert "timeout_s" in result
        assert "confidence" in result
        assert "sample_count" in result
        assert "operation" in result
        assert "based_on_history" in result
        assert "default_fallback" in result

        assert result["operation"] == "plan"
        assert result["sample_count"] == len(mock_durations)
        assert result["based_on_history"] is True
        assert result["default_fallback"] is False
        assert result["timeout_s"] > 0


def test_recommend_timeout_metadata_no_history():
    """Test metadata when no history available."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = []

        result = AdaptiveTimeoutService.recommend_timeout_with_metadata("plan")

        assert result["sample_count"] == 0
        assert result["based_on_history"] is False
        assert result["default_fallback"] is True
        assert result["timeout_s"] == AdaptiveTimeoutService.DEFAULT_TIMEOUTS["plan"]


def test_default_timeouts_coverage():
    """Test that all common operations have default timeouts."""
    operations = ["plan", "run", "merge", "recon", "validate"]

    for op in operations:
        assert op in AdaptiveTimeoutService.DEFAULT_TIMEOUTS
        assert AdaptiveTimeoutService.DEFAULT_TIMEOUTS[op] > 0


def test_percentile_calculation(mock_durations):
    """Test that percentile calculation is accurate."""
    with patch(PATCH_PATH) as mock_get:
        # Known distribution: [10, 20, 30, ..., 100]
        mock_get.return_value = mock_durations

        timeout = AdaptiveTimeoutService.predict_timeout("plan")

        # P95 of 10 values is index 9 (last value) = 100
        # With safety margin (1.2x): 100 * 1.2 = 120
        # No adjustments applied in this test
        expected_min = 100 * 1.2  # 120
        expected_max = 100 * 1.2 * 1.1  # 132 (allow 10% variance)

        assert expected_min <= timeout <= expected_max


def test_combined_adjustments(mock_durations):
    """Test that multiple adjustments compound correctly."""
    with patch(PATCH_PATH) as mock_get:
        mock_get.return_value = mock_durations

        # Apply multiple heavy adjustments
        timeout = AdaptiveTimeoutService.predict_timeout(
            "plan",
            context={
                "model": "claude-opus-4",  # +50%
                "system_load": "high",      # +30%
                "complexity": "complex",    # +40%
                "prompt_length": 2000,      # +20%
            }
        )

        # Base P95 ~= 100
        # Compounded: 100 * 1.5 * 1.3 * 1.4 * 1.2 * 1.2 (safety) ≈ 470
        # But capped at MAX_TIMEOUT (600)
        assert timeout <= AdaptiveTimeoutService.MAX_TIMEOUT
        assert timeout > 300  # Should be significantly higher than base
