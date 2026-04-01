"""Tests for graceful degradation in mastery endpoints."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def auth_headers(valid_token):
    """Auth headers using the canonical test token."""
    return {"Authorization": f"Bearer {valid_token}"}


@patch("tools.gimo_server.services.storage_service.StorageService")
def test_mastery_status_returns_200_when_storage_unavailable(mock_storage, test_client, auth_headers):
    """Mastery status returns 200 with zeros when StorageService fails."""
    mock_storage.side_effect = Exception("GICS detached")

    resp = test_client.get("/ops/mastery/status", headers=auth_headers)

    # Must return 200, not 500
    assert resp.status_code == 200

    data = resp.json()
    # Degrades gracefully with zeros
    assert data["total_savings_usd"] == 0.0
    assert data["efficiency_score"] >= 0.0
    assert isinstance(data["tips"], list)


@patch("tools.gimo_server.services.storage_service.StorageService")
def test_mastery_forecast_returns_empty_list_when_storage_fails(mock_storage, test_client, auth_headers):
    """Forecast returns empty list when StorageService unavailable."""
    mock_storage.side_effect = Exception("GICS detached")

    resp = test_client.get("/ops/mastery/forecast", headers=auth_headers)

    # Must return 200, not 500
    assert resp.status_code == 200

    data = resp.json()
    # Degrades to empty list
    assert data == []


@patch("tools.gimo_server.services.storage_service.StorageService")
def test_mastery_status_partial_data_when_alerts_fail(mock_storage, test_client, auth_headers):
    """Status returns partial data when budget alerts fail but savings work."""
    mock_store = MagicMock()
    mock_store.cost.get_total_savings.return_value = 10.50
    mock_store.cost.get_total_spend.return_value = 5.25
    mock_store.cost.check_budget_alerts.side_effect = Exception("Budget check failed")

    mock_storage.return_value = mock_store

    resp = test_client.get("/ops/mastery/status", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()

    # Savings work
    assert data["total_savings_usd"] == 10.50

    # Tips may be empty (alerts failed) but still returns successfully
    assert "tips" in data


def test_mastery_status_success_when_storage_healthy(test_client, auth_headers):
    """Status returns full data when StorageService healthy."""
    resp = test_client.get("/ops/mastery/status", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()

    # All MasteryStatus fields present
    assert "eco_mode_enabled" in data
    assert "total_savings_usd" in data
    assert "efficiency_score" in data
    assert "tips" in data
