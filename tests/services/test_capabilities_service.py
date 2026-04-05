"""Tests for CapabilitiesService - server-driven operation contracts."""
import pytest
from unittest.mock import MagicMock, patch
from tools.gimo_server.services.capabilities_service import CapabilitiesService
from tools.gimo_server.security.auth import AuthContext


@pytest.fixture
def mock_request():
    """Mock FastAPI request."""
    req = MagicMock()
    req.cookies.get.return_value = None
    req.app.state.gics = MagicMock()
    req.app.state.run_worker = True
    return req


@pytest.fixture
def mock_auth():
    """Mock auth context."""
    return AuthContext(token="test-token", role="operator")


@pytest.mark.asyncio
async def test_capabilities_returns_all_required_fields(mock_request, mock_auth):
    """Capabilities must return all contract fields."""
    caps = await CapabilitiesService.get_capabilities(mock_request, mock_auth)

    # Core fields
    assert "version" in caps
    assert "role" in caps
    assert "plan" in caps
    assert "features" in caps

    # Enhanced fields
    assert "active_model" in caps
    assert "active_provider" in caps
    assert "system_load" in caps
    assert "hints" in caps
    assert "service_health" in caps

    # Hints structure
    assert "generation_timeout_s" in caps["hints"]
    assert "default_timeout_s" in caps["hints"]
    assert caps["hints"]["default_timeout_s"] == 15

    # Service health structure
    assert "mastery" in caps["service_health"]
    assert "storage" in caps["service_health"]
    assert "generation" in caps["service_health"]
    assert "context" in caps["service_health"]


@pytest.mark.asyncio
@patch("tools.gimo_server.services.timeout.adaptive_timeout_service.AdaptiveTimeoutService.predict_timeout", side_effect=Exception("force static fallback"))
@patch("tools.gimo_server.services.hardware_monitor_service.HardwareMonitorService")
async def test_capabilities_adapts_timeout_to_system_load(mock_hw, _mock_ats, mock_request, mock_auth):
    """Generation timeout increases under high system load (static fallback path)."""
    # Safe load
    mock_hw.get_instance.return_value.get_load_level.return_value = "safe"
    caps = await CapabilitiesService.get_capabilities(mock_request, mock_auth)
    assert caps["hints"]["generation_timeout_s"] == 120

    # Caution load
    mock_hw.get_instance.return_value.get_load_level.return_value = "caution"
    caps = await CapabilitiesService.get_capabilities(mock_request, mock_auth)
    assert caps["hints"]["generation_timeout_s"] == 240

    # Critical load
    mock_hw.get_instance.return_value.get_load_level.return_value = "critical"
    caps = await CapabilitiesService.get_capabilities(mock_request, mock_auth)
    assert caps["hints"]["generation_timeout_s"] == 300


@pytest.mark.asyncio
async def test_capabilities_service_health_reflects_gics_state(mock_auth):
    """Service health degrades when GICS unavailable."""
    # GICS attached
    req = MagicMock()
    req.cookies.get.return_value = None
    req.app.state.gics = MagicMock()
    req.app.state.run_worker = True

    caps = await CapabilitiesService.get_capabilities(req, mock_auth)
    assert caps["service_health"]["mastery"] == "ok"
    assert caps["service_health"]["storage"] == "ok"

    # GICS detached
    req.app.state.gics = None
    caps = await CapabilitiesService.get_capabilities(req, mock_auth)
    assert caps["service_health"]["mastery"] == "degraded"
    assert caps["service_health"]["storage"] == "unavailable"


@pytest.mark.asyncio
@patch("tools.gimo_server.services.provider_service_impl.ProviderService")
async def test_capabilities_active_model_from_provider_service(mock_provider, mock_request, mock_auth):
    """Active model extracted from ProviderService config via primary_orchestrator_binding."""
    mock_binding = MagicMock()
    mock_binding.provider_id = "ollama"
    mock_binding.model = "qwen2.5-coder:3b"

    mock_cfg = MagicMock()
    mock_cfg.primary_orchestrator_binding.return_value = mock_binding
    mock_provider.get_config.return_value = mock_cfg

    caps = await CapabilitiesService.get_capabilities(mock_request, mock_auth)
    assert caps["active_provider"] == "ollama"
    assert caps["active_model"] == "qwen2.5-coder:3b"


@pytest.mark.asyncio
@patch("tools.gimo_server.services.provider_service_impl.ProviderService")
async def test_capabilities_handles_provider_service_failure(mock_provider, mock_request, mock_auth):
    """If ProviderService fails, returns None gracefully."""
    mock_provider.get_config.side_effect = Exception("Provider unavailable")

    caps = await CapabilitiesService.get_capabilities(mock_request, mock_auth)
    assert caps["active_model"] is None
    assert caps["active_provider"] is None
    # Still returns 200, not 500


@pytest.mark.asyncio
@patch("tools.gimo_server.services.capabilities_service.session_store")
async def test_capabilities_extracts_plan_from_firebase_session(mock_session_store, mock_auth):
    """Plan extracted from Firebase session when available."""
    req = MagicMock()
    req.cookies.get.return_value = "test-session-cookie"
    req.app.state.gics = MagicMock()
    req.app.state.run_worker = True

    mock_session = MagicMock()
    mock_session.plan = "pro"
    mock_session_store.validate.return_value = mock_session

    caps = await CapabilitiesService.get_capabilities(req, mock_auth)
    assert caps["plan"] == "pro"


@pytest.mark.asyncio
async def test_capabilities_defaults_to_local_plan(mock_request, mock_auth):
    """Without Firebase session, plan defaults to 'local'."""
    caps = await CapabilitiesService.get_capabilities(mock_request, mock_auth)
    assert caps["plan"] == "local"


@pytest.mark.asyncio
@patch("tools.gimo_server.services.hardware_monitor_service.HardwareMonitorService")
async def test_capabilities_handles_hardware_monitor_failure(mock_hw, mock_request, mock_auth):
    """If HardwareMonitorService fails, defaults to 'safe' load."""
    mock_hw.get_instance.side_effect = Exception("HW monitor crashed")

    caps = await CapabilitiesService.get_capabilities(mock_request, mock_auth)
    assert caps["system_load"] == "safe"
    # Adaptive timeout uses default for "plan" (180s) when no historical data
    assert caps["hints"]["generation_timeout_s"] == 180.0
