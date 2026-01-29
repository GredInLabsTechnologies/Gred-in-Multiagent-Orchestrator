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

client = TestClient(app)

@patch('tools.repo_orchestrator.main.REPO_ROOT_DIR', new=Path("/mock/repos"))
@patch('tools.repo_orchestrator.main.audit_log')
@patch('subprocess.Popen')
def test_api_open_repo_decoupled(mock_popen, mock_audit):
    """
    Verifies that open_repo is decoupled:
    1. Returns 200 OK.
    2. Logs the event.
    3. NEVER calls subprocess.Popen.
    """
    repo_path_str = "/mock/repos/myrepo"
    
    # Mock existence and resolution
    with patch('tools.repo_orchestrator.main.Path.exists', return_value=True):
        with patch('tools.repo_orchestrator.main.Path.resolve', return_value=Path(repo_path_str)):
            response = client.post(f"/ui/repos/open?path={repo_path_str}")
            
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
