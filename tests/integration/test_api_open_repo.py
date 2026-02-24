import pytest
import os
import sys
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from pathlib import Path

# Path injection
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext


@pytest.fixture(autouse=True)
def override_auth():
    def override_verify_token():
        return AuthContext(token="test-token-override", role="admin")
    app.dependency_overrides[verify_token] = override_verify_token
    yield


@patch('tools.gimo_server.routes.REPO_ROOT_DIR', new=Path("/mock/repos"))
@patch('tools.gimo_server.routes.audit_log')
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
            response = test_client.post(f"/ui/repos/open?path={repo_path_str}")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "server-agnostic" in data["message"]

            # Assertion: NEVER called subprocess
            mock_popen.assert_not_called()

            # Assertion: Audit log called
            mock_audit.assert_called_once_with("UI", "OPEN_REPO", str(Path(repo_path_str)), actor="test-token-override")

if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
