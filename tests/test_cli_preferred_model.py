"""Tests for X-Preferred-Model header propagation from CLI."""
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add parent dir to path for gimo.py import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gimo import _api_request


@pytest.fixture
def mock_config():
    """Mock CLI config."""
    return {
        "api": {
            "base_url": "http://localhost:9325",
            "timeout_seconds": 15.0,
        },
        "orchestrator": {
            "preferred_model": "claude-haiku-4-5-20251001"
        },
    }


@pytest.fixture
def mock_config_no_model():
    """Mock CLI config without preferred_model."""
    return {
        "api": {
            "base_url": "http://localhost:9325",
            "timeout_seconds": 15.0,
        },
        "orchestrator": {},
    }


@patch("gimo._resolve_token")
@patch("gimo._smart_timeout")
@patch("httpx.Client")
def test_preferred_model_sends_header(mock_client, mock_timeout, mock_token, mock_config):
    """When preferred_model set, X-Preferred-Model header sent."""
    mock_token.return_value = "test-token"
    mock_timeout.return_value = 15.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok"}

    mock_http = MagicMock()
    mock_http.__enter__.return_value.request.return_value = mock_resp
    mock_client.return_value = mock_http

    status, resp = _api_request(mock_config, "GET", "/ops/capabilities")

    # Verify header was sent
    call_args = mock_http.__enter__.return_value.request.call_args
    headers = call_args[1]["headers"]
    assert "X-Preferred-Model" in headers
    assert headers["X-Preferred-Model"] == "claude-haiku-4-5-20251001"


@patch("gimo._resolve_token")
@patch("gimo._smart_timeout")
@patch("httpx.Client")
def test_no_preferred_model_doesnt_send_header(mock_client, mock_timeout, mock_token, mock_config_no_model):
    """When preferred_model missing, X-Preferred-Model NOT sent."""
    mock_token.return_value = "test-token"
    mock_timeout.return_value = 15.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok"}

    mock_http = MagicMock()
    mock_http.__enter__.return_value.request.return_value = mock_resp
    mock_client.return_value = mock_http

    status, resp = _api_request(mock_config_no_model, "GET", "/ops/capabilities")

    # Verify header NOT sent
    call_args = mock_http.__enter__.return_value.request.call_args
    headers = call_args[1]["headers"]
    assert "X-Preferred-Model" not in headers


@patch("gimo._resolve_token")
@patch("gimo._smart_timeout")
@patch("httpx.Client")
def test_preferred_model_none_doesnt_crash(mock_client, mock_timeout, mock_token):
    """When preferred_model is None, doesn't crash."""
    mock_token.return_value = "test-token"
    mock_timeout.return_value = 15.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok"}

    mock_http = MagicMock()
    mock_http.__enter__.return_value.request.return_value = mock_resp
    mock_client.return_value = mock_http

    config = {
        "api": {"base_url": "http://localhost:9325", "timeout_seconds": 15.0},
        "orchestrator": {"preferred_model": None},
    }

    # Should not crash
    status, resp = _api_request(config, "GET", "/ops/capabilities")
    assert status == 200

    # Header should not be sent
    call_args = mock_http.__enter__.return_value.request.call_args
    headers = call_args[1]["headers"]
    assert "X-Preferred-Model" not in headers
