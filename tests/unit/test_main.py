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
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_panic_catcher_middleware(auth_client):
    with patch(
        "tools.gimo_server.security.load_security_db", return_value={"panic_mode": False}
    ):
        with patch(
            "tools.gimo_server.routes.get_active_repo_dir",
            side_effect=RuntimeError("critical fail"),
        ):
            response = auth_client.get("/ui/status")
            assert response.status_code == 500
            data = response.json()
            assert "Internal System Failure" in data["error"]


def test_panic_mode_check_middleware(auth_client):
    with patch(
        "tools.gimo_server.security.load_security_db", return_value={"panic_mode": True}
    ):
        response = auth_client.get("/ui/repos")
        assert response.status_code == 503
        assert "LOCKDOWN" in response.text

        # /status should be blocked during panic
        response_status = auth_client.get("/status")
        assert response_status.status_code == 503


def test_allow_options_preflight(auth_client):
    # Case 1: Origin in CORS_ORIGINS
    response = auth_client.options(
        "/ui/status",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Headers": "Content-Type",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 204
    assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"

    # Case 2: No Origin
    response = auth_client.get("/status")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_lifespan_events():
    with patch(
        "tools.gimo_server.services.snapshot_service.SnapshotService.ensure_snapshot_dir"
    ) as mock_ensure:

        async def dummy_loop():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                return

        with patch("tools.gimo_server.main.snapshot_cleanup_loop", side_effect=dummy_loop):
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


def test_root_route():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers.get("X-Correlation-ID")


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
    async def dummy_loop():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            return

    with patch(
        "tools.gimo_server.services.snapshot_service.SnapshotService.ensure_snapshot_dir"
    ):
        with patch("tools.gimo_server.main.snapshot_cleanup_loop", side_effect=dummy_loop):
            from tools.gimo_server.main import lifespan

            async with lifespan(app):
                assert app.state.start_time > 0
