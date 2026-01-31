import pytest
import os
import sys
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from pathlib import Path

# Path injection
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.repo_orchestrator.main import app
from tools.repo_orchestrator.security import verify_token

# Mock token dependency
async def override_verify_token():
    return "test_actor"

app.dependency_overrides[verify_token] = override_verify_token

@patch('tools.repo_orchestrator.routes.REPO_ROOT_DIR', new=Path("/mock/repos"))
@patch('tools.repo_orchestrator.routes.audit_log')
@patch('subprocess.Popen')
def test_api_open_repo_decoupled(mock_popen, mock_audit, test_client):
    """
    Verifies that open_repo is decoupled:
    1. Returns 200 OK.
    2. Logs the event.
    3. NEVER calls subprocess.Popen.
    """
    repo_path_str = "/mock/repos/myrepo"
    
    # Mock pathlib.Path.exists and resolve directly
    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.resolve', return_value=Path(repo_path_str)):
            # conftest.py sets ORCH_TOKEN to a specific test value
            token = os.environ.get("ORCH_TOKEN", "test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0")
            headers = {"Authorization": f"Bearer {token}"}
            response = test_client.post(f"/ui/repos/open?path={repo_path_str}", headers=headers)
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "server-agnostic" in data["message"]
            
            # Assertion: NEVER called subprocess
            mock_popen.assert_not_called()
            
            # Assertion: Audit log called
            mock_audit.assert_called_once_with("UI", "OPEN_REPO", str(Path(repo_path_str)), actor="test_actor")

if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
