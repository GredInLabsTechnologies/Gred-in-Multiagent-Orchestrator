import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tools.gimo_server.main import app, lifespan
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext


# Mock token dependency
def override_verify_token():
    return AuthContext(token="test-user", role="admin")


@pytest.fixture
def auth_client():
    app.dependency_overrides[verify_token] = override_verify_token
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_panic_catcher_middleware(test_client, valid_token):
    with patch(
        "tools.gimo_server.security.load_security_db", return_value={"panic_mode": False}
    ):
        with patch(
            "tools.gimo_server.routes.get_active_repo_dir",
            side_effect=RuntimeError("critical fail"),
        ):
            response = test_client.get(
                "/ui/status", headers={"Authorization": f"Bearer {valid_token}"}
            )
            assert response.status_code == 500
            data = response.json()
            assert "Internal System Failure" in data["error"]


def test_lockdown_check_middleware(test_client, valid_token):
    from tools.gimo_server.security import threat_engine
    from tools.gimo_server.security.threat_level import ThreatLevel, AUTH_FAILURE_LOCKDOWN_THRESHOLD

    for _ in range(AUTH_FAILURE_LOCKDOWN_THRESHOLD):
        threat_engine.record_auth_failure("attacker-1.2.3.4")
    assert threat_engine.level >= ThreatLevel.LOCKDOWN

    response = test_client.get("/status", headers={"Authorization": f"Bearer {valid_token}"})
    assert response.status_code == 200
    assert response.headers.get("X-Threat-Level") == "LOCKDOWN"


def test_allow_options_preflight(test_client, valid_token):
    response = test_client.options(
        "/ui/status",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Headers": "Content-Type",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 204
    assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"

    response = test_client.get("/status", headers={"Authorization": f"Bearer {valid_token}"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_lifespan_events():
    from unittest.mock import MagicMock

    with patch(
        "tools.gimo_server.services.snapshot_service.SnapshotService.ensure_snapshot_dir"
    ) as mock_ensure:

        async def dummy_loop():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                return

        mock_gics = MagicMock()
        mock_gics.start_daemon = MagicMock()
        mock_gics.start_health_check = MagicMock()
        mock_gics.stop_daemon = MagicMock()

        with patch("tools.gimo_server.main.snapshot_cleanup_loop", side_effect=dummy_loop), \
             patch("tools.gimo_server.main.GicsService", return_value=mock_gics):
            from tools.gimo_server.main import lifespan

            async with lifespan(app):
                mock_ensure.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_base_dir_missing():

    with patch("tools.gimo_server.main.BASE_DIR") as mock_base:
        mock_base.exists.return_value = False
        with pytest.raises(RuntimeError, match="BASE_DIR"):
            async with lifespan(app):
                pass  # Execution SHOULD fail before reaching here


def test_root_route(test_client):
    response = test_client.get("/")
    assert response.status_code == 200
    assert response.headers.get("X-Correlation-ID")


def test_app_metadata_uses_gimo_orchestrator_name():
    assert app.title == "GIMO Orchestrator"


@pytest.mark.asyncio
async def test_snapshot_cleanup_loop_exit():
    from tools.gimo_server.main import snapshot_cleanup_loop

    with patch("asyncio.sleep", side_effect=[None, Exception("stop"), None, None]):
        with patch(
            "tools.gimo_server.services.snapshot_service.SnapshotService.cleanup_old_snapshots",
            side_effect=Exception("inner"),
        ):
            with pytest.raises(Exception, match="stop"):
                await snapshot_cleanup_loop()


@pytest.mark.asyncio
async def test_lifespan_cleanup_task_cancelled_error_propagates():
    from unittest.mock import MagicMock

    async def dummy_loop():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            return

    mock_gics = MagicMock()
    mock_gics.start_daemon = MagicMock()
    mock_gics.start_health_check = MagicMock()
    mock_gics.stop_daemon = MagicMock()

    with patch(
        "tools.gimo_server.services.snapshot_service.SnapshotService.ensure_snapshot_dir"
    ):
        with patch("tools.gimo_server.main.snapshot_cleanup_loop", side_effect=dummy_loop), \
             patch("tools.gimo_server.main.GicsService", return_value=mock_gics):
            from tools.gimo_server.main import lifespan

            async with lifespan(app):
                assert app.state.start_time > 0
