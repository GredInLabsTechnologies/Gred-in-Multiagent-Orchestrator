import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Path injection
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.repo_orchestrator.main import app
from tools.repo_orchestrator.security import verify_token
from tools.repo_orchestrator.security.auth import AuthContext


def override_verify_token(actor: str):
    return AuthContext(token=actor, role="admin")


@patch("tools.repo_orchestrator.routes.REPO_ROOT_DIR", new=Path("/mock/repos"))
@patch("tools.repo_orchestrator.routes.audit_log")
@patch("subprocess.Popen")
def test_api_open_repo_decoupled(mock_popen, mock_audit, test_client, valid_token, test_actor):
    """
    Verifies that open_repo is decoupled:
    1. Returns 200 OK.
    2. Logs the event.
    3. NEVER calls subprocess.Popen.
    """
    repo_path_str = "/mock/repos/myrepo"

    app.dependency_overrides[verify_token] = lambda: override_verify_token(test_actor)
    try:
        # Mock pathlib.Path.exists and resolve directly
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.resolve", return_value=Path(repo_path_str)):
                # conftest.py sets ORCH_TOKEN to a specific test value
                headers = {"Authorization": f"Bearer {valid_token}"}
                response = test_client.post(f"/ui/repos/open?path={repo_path_str}", headers=headers)

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "success"
                assert "server-agnostic" in data["message"]

                # Assertion: NEVER called subprocess
                mock_popen.assert_not_called()

                # Assertion: Audit log called
                mock_audit.assert_called_once_with(
                    "UI", "OPEN_REPO", str(Path(repo_path_str)), actor=test_actor
                )
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
