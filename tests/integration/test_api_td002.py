import pytest
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Path injection
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext


@pytest.fixture(autouse=True)
def override_auth():
    """Re-apply auth override before each test (survives conftest cleanup)."""
    def override_verify_token():
        return AuthContext(token="test-token-override", role="admin")
    app.dependency_overrides[verify_token] = override_verify_token
    yield


@pytest.fixture(autouse=True)
def setup_headless():
    os.environ["ORCH_HEADLESS"] = "true"
    yield
    if "ORCH_HEADLESS" in os.environ:
        del os.environ["ORCH_HEADLESS"]

def test_api_service_status(test_client):
    with patch('tools.gimo_server.routes.SystemService.get_status') as mock_status:
        mock_status.return_value = "RUNNING"
        response = test_client.get("/ui/service/status")
        assert response.status_code == 200
        assert response.json() == {"status": "RUNNING"}

def test_api_service_restart(test_client):
    with patch('tools.gimo_server.routes.SystemService.restart') as mock_restart:
        mock_restart.return_value = True
        response = test_client.post("/ui/service/restart")
        assert response.status_code == 200
        assert response.json() == {"status": "restarting"}
        mock_restart.assert_called_once()

def test_api_service_stop(test_client):
    with patch('tools.gimo_server.routes.SystemService.stop') as mock_stop:
        mock_stop.return_value = True
        response = test_client.post("/ui/service/stop")
        assert response.status_code == 200
        assert response.json() == {"status": "stopping"}
        mock_stop.assert_called_once()

def test_api_vitaminize_invalid_path(test_client):
    response = test_client.post("/ui/repos/vitaminize?path=C:/outside")
    # 400 on Windows (invalid path), 404 on Linux (path not found)
    assert response.status_code in (400, 404)

def test_api_vitaminize_success(test_client):
    """Use sequential patching for better control and debugging"""
    with patch('tools.gimo_server.routes.REPO_ROOT_DIR', new=Path("/mock/repos")):
        with patch('tools.gimo_server.routes.RepoService.vitaminize_repo') as mock_vit:
            mock_vit.return_value = ["file1.txt", "file2.txt"]
            with patch('pathlib.Path.exists', return_value=True):
                with patch('pathlib.Path.resolve', return_value=MagicMock(__str__=lambda x: "/mock/repos/myrepo")):
                    with patch('tools.gimo_server.routes.load_repo_registry', return_value={}):
                        with patch('tools.gimo_server.routes.save_repo_registry'):
                            response = test_client.post("/ui/repos/vitaminize?path=/mock/repos/myrepo")
                            assert response.status_code == 200
                            data = response.json()
                            assert data["status"] == "success"
                            assert len(data["created_files"]) == 2
                            assert "active_repo" in data

if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
