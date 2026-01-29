import pytest
import os
import sys
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Path injection
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.repo_orchestrator.main import app
from tools.repo_orchestrator.security import verify_token

# Mock token dependency
async def override_verify_token():
    return "test_actor"

app.dependency_overrides[verify_token] = override_verify_token

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_headless():
    os.environ["ORCH_HEADLESS"] = "true"
    yield
    if "ORCH_HEADLESS" in os.environ:
        del os.environ["ORCH_HEADLESS"]

def test_api_service_status():
    with patch('tools.repo_orchestrator.services.system_service.SystemService.get_status') as mock_status:
        mock_status.return_value = "RUNNING"
        response = client.get("/ui/service/status")
        assert response.status_code == 200
        assert response.json() == {"status": "RUNNING"}

def test_api_service_restart():
    with patch('tools.repo_orchestrator.services.system_service.SystemService.restart') as mock_restart:
        mock_restart.return_value = True
        response = client.post("/ui/service/restart")
        assert response.status_code == 200
        assert response.json() == {"status": "restarting"}
        mock_restart.assert_called_once()

def test_api_service_stop():
    with patch('tools.repo_orchestrator.services.system_service.SystemService.stop') as mock_stop:
        mock_stop.return_value = True
        response = client.post("/ui/service/stop")
        assert response.status_code == 200
        assert response.json() == {"status": "stopping"}
        mock_stop.assert_called_once()

def test_api_vitaminize_invalid_path():
    response = client.post("/ui/repos/vitaminize?path=C:/outside")
    assert response.status_code == 400

@patch('tools.repo_orchestrator.main._vitaminize_repo')
@patch('tools.repo_orchestrator.main.REPO_ROOT_DIR', new="/mock/repos")
def test_api_vitaminize_success(mock_vit):
    mock_vit.return_value = ["file1.txt", "file2.txt"]
    # Ensure path exists for validation
    with patch('tools.repo_orchestrator.main.Path.exists', return_value=True):
        with patch('tools.repo_orchestrator.main.Path.resolve', return_value=MagicMock(__str__=lambda x: "/mock/repos/myrepo")):
            with patch('tools.repo_orchestrator.main.load_repo_registry', return_value={"repos": []}):
                with patch('tools.repo_orchestrator.main.save_repo_registry'):
                    response = client.post("/ui/repos/vitaminize?path=/mock/repos/myrepo")
                    assert response.status_code == 200
                    data = response.json()
                    assert data["status"] == "success"
                    assert len(data["created_files"]) == 2
                    assert "active_repo" in data

if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
