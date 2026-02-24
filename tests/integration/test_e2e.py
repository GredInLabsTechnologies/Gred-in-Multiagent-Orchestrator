import os

from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.version import __version__


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("ORCH_TOKEN", "test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0")
    return {"Authorization": f"Bearer {token}"}


def test_e2e_status_endpoints():
    """Minimal E2E harness validating core status endpoints with auth."""
    with TestClient(app, raise_server_exceptions=False) as client:
        status_response = client.get("/status", headers=_auth_headers())
        assert status_response.status_code == 200
        payload = status_response.json()
        assert payload.get("version") == __version__
        assert payload.get("uptime_seconds", 0) >= 0

        ui_response = client.get("/ui/status", headers=_auth_headers())
        assert ui_response.status_code == 200
        ui_payload = ui_response.json()
        assert ui_payload.get("version") == __version__
        assert ui_payload.get("service_status")
