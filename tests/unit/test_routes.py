import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.models import RepoEntry
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext


# Mock token dependency for all route tests
def override_verify_token():
    return AuthContext(token="test-user", role="admin")


@pytest.fixture
def client():
    app.dependency_overrides[verify_token] = override_verify_token
    app.state.start_time = time.time()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_get_status(client):
    response = client.get("/status")
    assert response.status_code == 200
    assert "version" in response.json()


def test_get_ui_status(client):
    with patch(
        "tools.gimo_server.routes.FileService.tail_audit_lines", return_value=["audit line"]
    ):
        with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=Path(".")):
            response = client.get("/ui/status")
            assert response.status_code == 200
            assert response.json()["last_audit_line"] == "audit line"


def test_get_ui_audit(client):
    with patch(
        "tools.gimo_server.routes.FileService.tail_audit_lines", return_value=["l1", "l2"]
    ):
        response = client.get("/ui/audit?limit=10")
        assert response.status_code == 200
        assert len(response.json()["lines"]) == 2


def test_get_ui_allowlist(client, tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    f = base / "file.py"
    f.write_text("ok")
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=base):
        with patch("tools.gimo_server.routes.get_allowed_paths", return_value={f}):
            with patch(
                "tools.gimo_server.routes.serialize_allowlist",
                return_value=[
                    {"path": str(f), "type": "file"},
                    {"path": "/outside", "type": "file"},
                ],
            ):
                response = client.get("/ui/allowlist")
                assert response.status_code == 200
                assert response.json()["paths"][0]["path"] == "file.py"
                assert len(response.json()["paths"]) == 1


def test_list_repos(client):
    with patch(
        "tools.gimo_server.routes.RepoService.list_repos",
        return_value=[
            RepoEntry(name="r1", path="C:\\Users\\someuser\\repo"),
            RepoEntry(name="empty", path=""),
        ],
    ):
        with patch(
            "tools.gimo_server.routes.RepoService.ensure_repo_registry",
            return_value={"active_repo": "C:\\Users\\someuser\\repo"},
        ):
            # Use a generic user path to avoid hardcoding a real workstation username.
            with patch("tools.gimo_server.routes.REPO_ROOT_DIR", Path("C:\\Users\\someuser")):
                response = client.get("/ui/repos")
                assert response.status_code == 200
                assert "[USER]" in response.json()["active_repo"]
                assert response.json()["repos"][1]["path"] == ""


def test_get_active_repo(client):
    with patch(
        "tools.gimo_server.routes.load_repo_registry",
        return_value={"active_repo": "/mock/active"},
    ):
        response = client.get("/ui/repos/active")
        assert response.status_code == 200
        assert response.json()["active_repo"] == "/mock/active"


def test_open_repo_success(client, tmp_path):
    with patch("tools.gimo_server.routes.REPO_ROOT_DIR", tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        response = client.post(f"/ui/repos/open?path={repo}")
        assert response.status_code == 200


def test_open_repo_fail_outside(client, tmp_path):
    with patch("tools.gimo_server.routes.REPO_ROOT_DIR", tmp_path / "root"):
        response = client.post(f"/ui/repos/open?path={tmp_path / 'outside'}")
        assert response.status_code == 400


def test_open_repo_fail_not_found(client, tmp_path):
    with patch("tools.gimo_server.routes.REPO_ROOT_DIR", tmp_path):
        response = client.post(f"/ui/repos/open?path={tmp_path / 'nonexistent'}")
        assert response.status_code == 404


def test_select_repo_success(client, tmp_path):
    with patch("tools.gimo_server.routes.REPO_ROOT_DIR", tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        with patch("tools.gimo_server.routes.load_repo_registry", return_value={"repos": []}):
            with patch("tools.gimo_server.routes.save_repo_registry") as mock_save:
                response = client.post(f"/ui/repos/select?path={repo}")
                assert response.status_code == 200
                mock_save.assert_called_once()
                assert response.json()["active_repo"] == str(repo.resolve())


def test_select_repo_fail_outside(client, tmp_path):
    with patch("tools.gimo_server.routes.REPO_ROOT_DIR", tmp_path / "root"):
        response = client.post(f"/ui/repos/select?path={tmp_path / 'outside'}")
        assert response.status_code == 400


def test_select_repo_fail_not_found(client, tmp_path):
    with patch("tools.gimo_server.routes.REPO_ROOT_DIR", tmp_path):
        response = client.post(f"/ui/repos/select?path={tmp_path / 'nonexistent'}")
        assert response.status_code == 404


def test_get_security_events(client):
    with patch(
        "tools.gimo_server.routes.load_security_db",
        return_value={"panic_mode": False, "recent_events": []},
    ):
        response = client.get("/ui/security/events")
        assert response.status_code == 200
        assert response.json()["panic_mode"] is False


def test_security_resolve_success(client):
    with patch(
        "tools.gimo_server.routes.load_security_db",
        return_value={"panic_mode": True, "recent_events": [{"resolved": False}]},
    ):
        with patch("tools.gimo_server.routes.save_security_db") as mock_save:
            response = client.post("/ui/security/resolve?action=clear_panic")
            assert response.status_code == 200
            db = mock_save.call_args[0][0]
            assert db["panic_mode"] is False
            assert db["recent_events"][0]["resolved"] is True


def test_security_resolve_invalid(client):
    response = client.post("/ui/security/resolve?action=invalid")
    assert response.status_code == 400


def test_get_service_status(client):
    with patch("tools.gimo_server.routes.SystemService.get_status", return_value="RUNNING"):
        response = client.get("/ui/service/status")
        assert response.status_code == 200
        assert response.json()["status"] == "RUNNING"


def test_service_restart_success(client):
    with patch("tools.gimo_server.routes.SystemService.restart", return_value=True):
        response = client.post("/ui/service/restart")
        assert response.status_code == 200


def test_service_restart_fail(client):
    with patch("tools.gimo_server.routes.SystemService.restart", return_value=False):
        response = client.post("/ui/service/restart")
        assert response.status_code == 500


def test_service_stop_success(client):
    with patch("tools.gimo_server.routes.SystemService.stop", return_value=True):
        response = client.post("/ui/service/stop")
        assert response.status_code == 200


def test_service_stop_fail(client):
    with patch("tools.gimo_server.routes.SystemService.stop", return_value=False):
        response = client.post("/ui/service/stop")
        assert response.status_code == 500


def test_vitaminize_repo_success(client, tmp_path):
    repo = tmp_path / "v-repo"
    repo.mkdir()
    with patch("tools.gimo_server.routes.REPO_ROOT_DIR", tmp_path):
        with patch(
            "tools.gimo_server.routes.RepoService.vitaminize_repo", return_value=["vit"]
        ):
            with patch("tools.gimo_server.routes.load_repo_registry", return_value={}):
                with patch("tools.gimo_server.routes.save_repo_registry"):
                    response = client.post(f"/ui/repos/vitaminize?path={repo}")
                    assert response.status_code == 200


def test_vitaminize_repo_fail_outside(client, tmp_path):
    with patch("tools.gimo_server.routes.REPO_ROOT_DIR", tmp_path / "root"):
        response = client.post(f"/ui/repos/vitaminize?path={tmp_path / 'outside'}")
        assert response.status_code == 400


def test_vitaminize_repo_fail_not_found(client, tmp_path):
    with patch("tools.gimo_server.routes.REPO_ROOT_DIR", tmp_path):
        response = client.post(f"/ui/repos/vitaminize?path={tmp_path / 'none'}")
        assert response.status_code == 404


def test_get_tree_success(client, tmp_path):
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routes.validate_path", return_value=tmp_path):
            with patch(
                "tools.gimo_server.routes.RepoService.walk_tree", return_value=["f1.py"]
            ):
                with patch("tools.gimo_server.routes.ALLOWLIST_REQUIRE", False):
                    response = client.get("/tree?path=.")
                    assert response.status_code == 200
                    assert "f1.py" in response.json()["files"]


def test_get_tree_allowlist_branch(client, tmp_path):
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routes.validate_path", return_value=tmp_path):
            with patch("tools.gimo_server.routes.ALLOWLIST_REQUIRE", True):
                with patch(
                    "tools.gimo_server.routes.get_allowed_paths",
                    return_value={tmp_path / "allowed.txt"},
                ):
                    response = client.get("/tree?path=.")
                    assert response.status_code == 200
                    assert "allowed.txt" in response.json()["files"]


def test_get_tree_not_dir(client, tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("ok")
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routes.validate_path", return_value=f):
            response = client.get("/tree?path=f.txt")
            assert response.status_code == 400


def test_get_file_success(client, tmp_path):
    f = tmp_path / "test.py"
    f.write_text("content")
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routes.validate_path", return_value=f):
            with patch(
                "tools.gimo_server.routes.FileService.get_file_content",
                return_value=("content", "hash"),
            ):
                response = client.get("/file?path=test.py")
                assert response.status_code == 200
                assert response.text == "content"


def test_get_file_too_large(client, tmp_path):
    f = tmp_path / "large.py"
    f.write_text("a")
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routes.validate_path", return_value=f):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 10 * 1024 * 1024
                mock_stat.return_value.st_mode = 0o100644  # Regular file
                response = client.get("/file?path=large.py")
                assert response.status_code == 413


def test_get_file_not_file(client, tmp_path):
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routes.validate_path", return_value=tmp_path):
            response = client.get("/file?path=.")
            assert response.status_code == 400


def test_get_file_exception(client, tmp_path):
    f = tmp_path / "test.py"
    f.write_text("ok")
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routes.validate_path", return_value=f):
            with patch(
                "tools.gimo_server.routes.FileService.get_file_content",
                side_effect=Exception("oops"),
            ):
                response = client.get("/file?path=test.py")
                assert response.status_code == 500


def test_search(client, tmp_path):
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=tmp_path):
        with patch(
            "tools.gimo_server.routes.RepoService.perform_search",
            return_value=[{"file": "a.py"}],
        ):
            response = client.get("/search?q=query")
            assert response.status_code == 200
            assert len(response.json()["results"]) == 1


def test_diff_success(client, tmp_path):
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=tmp_path):
        with patch(
            "tools.gimo_server.services.git_service.GitService.get_diff",
            return_value="diff data",
        ):
            response = client.get("/diff")
            assert response.status_code == 200
            assert response.text == "diff data"


def test_diff_truncated(client, tmp_path):
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=tmp_path):
        # Use a string that won't be redacted but IS long
        long_diff = "line\n" * 100
        with patch(
            "tools.gimo_server.services.git_service.GitService.get_diff",
            return_value=long_diff,
        ):
            with patch("tools.gimo_server.config.MAX_BYTES", 10):
                response = client.get("/diff")
                assert response.status_code == 200
                assert "TRUNCATED" in response.text


def test_diff_error(client, tmp_path):
    with patch("tools.gimo_server.routes.get_active_repo_dir", return_value=tmp_path):
        with patch(
            "tools.gimo_server.services.git_service.GitService.get_diff",
            side_effect=Exception("git fail"),
        ):
            response = client.get("/diff")
            assert response.status_code == 400
            assert "git fail" in response.json()["detail"]
