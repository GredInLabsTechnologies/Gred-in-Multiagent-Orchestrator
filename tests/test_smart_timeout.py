"""Tests for _smart_timeout() - server-driven timeout selection."""
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add parent dir to path for gimo.py import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gimo import _smart_timeout, _fetch_capabilities


@pytest.fixture
def mock_config():
    """Mock CLI config."""
    return {
        "api": {
            "base_url": "http://localhost:9325",
            "timeout_seconds": 15.0,
        },
        "orchestrator": {},
    }


@patch("gimo._fetch_capabilities")
def test_smart_timeout_generation_endpoints_use_server_hint(mock_fetch, mock_config):
    """Generation endpoints use server-provided timeout hint."""
    mock_fetch.return_value = {
        "hints": {
            "generation_timeout_s": 180,
            "default_timeout_s": 15,
        }
    }

    timeout = _smart_timeout("/ops/generate-plan", mock_config)
    assert timeout == 180.0

    timeout = _smart_timeout("/ops/slice0-pipeline", mock_config)
    assert timeout == 180.0

    timeout = _smart_timeout("/ops/threads/123/chat", mock_config)
    assert timeout == 180.0


@patch("gimo._fetch_capabilities")
def test_smart_timeout_stream_endpoints_have_no_timeout(mock_fetch, mock_config):
    """Stream endpoints return None (no timeout)."""
    mock_fetch.return_value = {"hints": {}}

    timeout = _smart_timeout("/ops/stream", mock_config)
    assert timeout is None

    timeout = _smart_timeout("/ops/chat", mock_config)
    assert timeout is None


@patch("gimo._fetch_capabilities")
def test_smart_timeout_default_endpoints_use_15s(mock_fetch, mock_config):
    """Default endpoints use 15s from server hint."""
    mock_fetch.return_value = {
        "hints": {
            "generation_timeout_s": 120,
            "default_timeout_s": 15,
        }
    }

    timeout = _smart_timeout("/ops/runs/123", mock_config)
    assert timeout == 15.0

    timeout = _smart_timeout("/ops/mastery/status", mock_config)
    assert timeout == 15.0


@patch("gimo._fetch_capabilities")
def test_smart_timeout_fallback_when_server_unreachable(mock_fetch, mock_config):
    """When server unreachable, falls back to local defaults."""
    mock_fetch.return_value = {}  # Empty dict = fetch failed

    # Generation endpoints fallback to 180s
    timeout = _smart_timeout("/ops/generate-plan", mock_config)
    assert timeout == 180.0

    # Default endpoints fallback to 15s
    timeout = _smart_timeout("/ops/runs/123", mock_config)
    assert timeout == 15.0

    # Streams still no timeout
    timeout = _smart_timeout("/ops/stream", mock_config)
    assert timeout is None


@patch("gimo._fetch_capabilities")
def test_smart_timeout_adapts_to_system_load(mock_fetch, mock_config):
    """Timeout increases when server reports high load."""
    # Critical load → 300s
    mock_fetch.return_value = {
        "system_load": "critical",
        "hints": {"generation_timeout_s": 300}
    }
    timeout = _smart_timeout("/ops/generate-plan", mock_config)
    assert timeout == 300.0

    # Normal load → 120s
    mock_fetch.return_value = {
        "system_load": "normal",
        "hints": {"generation_timeout_s": 120}
    }
    timeout = _smart_timeout("/ops/generate-plan", mock_config)
    assert timeout == 120.0


@patch("gimo._fetch_capabilities")
def test_smart_timeout_missing_hints_uses_safe_defaults(mock_fetch, mock_config):
    """Missing hints field uses safe hardcoded defaults."""
    mock_fetch.return_value = {}  # No hints at all

    timeout = _smart_timeout("/ops/generate-plan", mock_config)
    assert timeout == 180.0  # Safe default for generation

    timeout = _smart_timeout("/ops/status", mock_config)
    assert timeout == 15.0  # Safe default for queries
