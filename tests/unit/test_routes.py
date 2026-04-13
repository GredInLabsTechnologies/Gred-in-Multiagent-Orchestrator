import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tools.gimo_server.main import app
from tools.gimo_server.mcp_bridge.manifest import MANIFEST
from tools.gimo_server.models import RepoEntry
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.services.conversation_service import ConversationService


# Mock token dependency for all route tests
def override_verify_token():
    return AuthContext(token="test-user", role="admin")


@pytest.fixture
def client():
    app.dependency_overrides[verify_token] = override_verify_token
    app.state.start_time = time.time()
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_get_status(client):
    response = client.get("/status")
    assert response.status_code == 200
    assert "version" in response.json()


def test_ui_plan_create_writes_canonical_plan_content(client):
    raw_plan = {
        "id": "plan_1",
        "title": "Ship feature",
        "workspace": ".",
        "created": "2026-03-28",
        "objective": "Implement change",
        "tasks": [
            {
                "id": "t1",
                "title": "Investigate API",
                "description": "Read docs and understand the endpoint",
                "scope": "file_write",
                "depends": [],
                "status": "pending",
                "agent_assignee": {
                    "role": "worker",
                    "goal": "Understand the API shape",
                    "backstory": "Senior investigator",
                    "model": "gpt-4o",
                    "system_prompt": "Be thorough.",
                    "instructions": ["Inspect the API carefully."],
                },
            }
        ],
    }

    captured = {}

    def _capture_create_draft(**kwargs):
        captured["content"] = kwargs["content"]
        return type(
            "Draft",
            (),
            {
                "id": "d_ui_1",
                "status": "draft",
                "prompt": kwargs["prompt"],
                "content": kwargs["content"],
            },
        )()

    async def _fake_generate(*_args, **_kwargs):
        return {"content": json.dumps(raw_plan)}

    with patch(
        "tools.gimo_server.routers.legacy_ui_router.ProviderService.static_generate",
        new=_fake_generate,
    ), patch(
        "tools.gimo_server.routers.legacy_ui_router.OpsService.create_draft",
        side_effect=_capture_create_draft,
    ):
        response = client.post("/ui/plan/create", json={"prompt": "ship p2"})

    assert response.status_code == 200
    payload = json.loads(captured["content"])
    assert payload["tasks"][0]["task_descriptor"]["task_id"] == "t1"
    assert "task_fingerprint" in payload["tasks"][0]


def test_get_health_deep(client, tmp_path):
    with patch("tools.gimo_server.routers.legacy_ui_router.ProviderService.health_check", return_value=True):
        with patch("tools.gimo_server.routers.legacy_ui_router.OpsService.OPS_DIR", tmp_path):
            response = client.get("/health/deep")
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "ok"
            assert payload["checks"]["provider_health"] is True
            assert payload["checks"]["ops_dir_exists"] is True


def test_cold_room_access_success(client):
    with patch("tools.gimo_server.routers.auth_router._cold_room_enabled", return_value=True):
        manager = MagicMock()
        manager.get_status.return_value = {
            "paired": True,
            "renewal_valid": True,
            "plan": "enterprise_cold_room",
        }
        with patch("tools.gimo_server.routers.auth_router._get_cold_room_manager", return_value=manager):
            response = client.post("/auth/cold-room/access")
            assert response.status_code == 200
            payload = response.json()
            assert payload["role"] == "operator"
            assert "Authenticated" in payload["message"]


def test_cold_room_access_not_paired(client):
    with patch("tools.gimo_server.routers.auth_router._cold_room_enabled", return_value=True):
        manager = MagicMock()
        manager.get_status.return_value = {
            "paired": False,
            "renewal_valid": False,
        }
        with patch("tools.gimo_server.routers.auth_router._get_cold_room_manager", return_value=manager):
            response = client.post("/auth/cold-room/access")
            assert response.status_code == 401
            assert response.json()["detail"] == "cold_room_not_paired"


def test_cold_room_access_renewal_required(client):
    with patch("tools.gimo_server.routers.auth_router._cold_room_enabled", return_value=True):
        manager = MagicMock()
        manager.get_status.return_value = {
            "paired": True,
            "renewal_valid": False,
        }
        with patch("tools.gimo_server.routers.auth_router._get_cold_room_manager", return_value=manager):
            response = client.post("/auth/cold-room/access")
            assert response.status_code == 401
            assert response.json()["detail"] == "cold_room_renewal_required"


def test_cold_room_access_disabled(client):
    with patch("tools.gimo_server.routers.auth_router._cold_room_enabled", return_value=False):
        response = client.post("/auth/cold-room/access")
        assert response.status_code == 404


def test_get_ui_hardware(client):
    fake_hw = MagicMock()
    fake_hw.get_current_state.return_value = {"cpu_percent": 12.5}
    fake_hw.is_local_safe.return_value = True
    fake_models = [
        MagicMock(is_local=True),
        MagicMock(is_local=False),
    ]
    with patch("tools.gimo_server.services.hardware_monitor_service.HardwareMonitorService.get_instance", return_value=fake_hw):
        with patch("tools.gimo_server.services.model_inventory_service.ModelInventoryService.get_available_models", return_value=fake_models):
            response = client.get("/ui/hardware")
            assert response.status_code == 200
            payload = response.json()
            assert payload["cpu_percent"] == 12.5
            assert payload["available_models"] == 2
            assert payload["local_models"] == 1
            assert payload["remote_models"] == 1
            assert payload["local_safe"] is True


def test_get_me_uses_cookie_session(client):
    fake_session = MagicMock(
        email="user@example.com",
        display_name="Test User",
        plan="pro",
        firebase_user=True,
        role="admin",
    )
    with patch("tools.gimo_server.routers.core_router.session_store.validate", return_value=fake_session):
        response = client.get("/me", cookies={"gimo_session": "session-token"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["email"] == "user@example.com"
        assert payload["plan"] == "pro"
        assert payload["firebaseUser"] is True


def test_get_ui_audit(client):
    with patch(
        "tools.gimo_server.routers.legacy_ui_router.FileService.tail_audit_lines", return_value=["l1", "l2"]
    ):
        response = client.get("/ui/audit?limit=10")
        assert response.status_code == 200
        assert len(response.json()["lines"]) == 2


def test_get_ui_allowlist(client, tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    f = base / "file.py"
    f.write_text("ok")
    with patch("tools.gimo_server.routers.legacy_ui_router.get_active_repo_dir", return_value=base):
        with patch("tools.gimo_server.routers.legacy_ui_router.get_allowed_paths", return_value={f}):
            with patch(
                "tools.gimo_server.routers.legacy_ui_router.serialize_allowlist",
                return_value=[
                    {"path": str(f), "type": "file"},
                    {"path": "/outside", "type": "file"},
                ],
            ):
                response = client.get("/ui/allowlist")
                assert response.status_code == 200
                assert response.json()["paths"][0]["path"] == "file.py"
                assert len(response.json()["paths"]) == 1


def test_ui_provider_legacy_routes_absent_from_router_table():
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/ui/nodes" not in route_paths
    assert "/ui/status" not in route_paths
    assert "/ui/providers" not in route_paths
    assert "/ui/providers/{provider_id}" not in route_paths
    assert "/ui/providers/{provider_id}/test" not in route_paths


@pytest.mark.parametrize(
    "path",
    [
        "/ui/status",
        "/ui/nodes",
        "/ui/providers",
        "/ui/providers/openai-main",
        "/ui/providers/openai-main/test",
    ],
)
def test_ui_provider_legacy_paths_return_not_found_for_get(client, path):
    response = client.get(path)
    assert response.status_code == 404


def test_mcp_bridge_manifest_does_not_publish_legacy_provider_routes():
    assert not any(str(entry.get("path", "")) == "/ui/status" for entry in MANIFEST)
    assert not any(str(entry.get("path", "")).startswith("/ui/providers") for entry in MANIFEST)
    assert not any(str(entry.get("path", "")) == "/ui/nodes" for entry in MANIFEST)


def test_list_repos(client, tmp_path):
    repo_dir = tmp_path / "my_repo"
    repo_dir.mkdir()
    with patch(
        "tools.gimo_server.routers.ops.repo_router.load_repo_registry",
        return_value={"active_repo": str(repo_dir), "repos": [str(repo_dir)]},
    ):
        with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path):
            response = client.get("/ops/repos")
            assert response.status_code == 200
            assert len(response.json()["repos"]) == 1
            assert response.json()["repos"][0]["name"] == "my_repo"


def test_get_active_repo(client):
    with patch(
        "tools.gimo_server.routers.ops.repo_router.load_repo_registry",
        return_value={"active_repo": "/mock/active"},
    ):
        response = client.get("/ops/repos/active")
        assert response.status_code == 200
        assert response.json()["active_repo"] == "/mock/active"


def test_get_active_repo_with_override(client):
    with patch(
        "tools.gimo_server.routers.ops.repo_router.RepoOverrideService.get_active_override",
        return_value={
            "repo_id": "/mock/override",
            "etag": '"abc"',
            "expires_at": "2099-01-01T00:00:00Z",
            "set_by_user": "operator",
        },
    ):
        response = client.get("/ops/repos/active")
        assert response.status_code == 200
        assert response.json()["active_repo"] == "/mock/override"
        assert response.json()["override_active"] is True
        assert response.headers.get("etag") == '"abc"'


def test_open_repo_success(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        response = client.post(f"/ops/repos/open?path={repo}")
        assert response.status_code == 200


def test_add_turn_route_rejects_unsupported_agent_id(client, tmp_path):
    original_threads_dir = ConversationService.THREADS_DIR
    ConversationService.THREADS_DIR = tmp_path / "threads"
    try:
        thread = ConversationService.create_thread(workspace_root=str(tmp_path), title="turn-guard")

        response = client.post(f"/ops/threads/{thread.id}/turns?agent_id=123-invalid")

        assert response.status_code == 400
        assert "Invalid agent_id" in response.json()["detail"]
    finally:
        ConversationService.THREADS_DIR = original_threads_dir


def test_open_repo_fail_outside(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path / "root"):
        response = client.post(f"/ops/repos/open?path={tmp_path / 'outside'}")
        assert response.status_code == 400


def test_open_repo_fail_not_found(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path):
        response = client.post(f"/ops/repos/open?path={tmp_path / 'nonexistent'}")
        assert response.status_code == 404


def test_open_repo_operator_forbidden(tmp_path):
    def override_operator():
        return AuthContext(token="operator-token", role="operator")

    app.dependency_overrides[verify_token] = override_operator
    client = TestClient(app, raise_server_exceptions=False)
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        response = client.post(f"/ops/repos/open?path={repo}")
        assert response.status_code == 403
    app.dependency_overrides.clear()


def test_select_repo_success(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        with patch("tools.gimo_server.routers.ops.repo_router.load_repo_registry", return_value={"repos": []}):
            with patch("tools.gimo_server.routers.ops.repo_router.save_repo_registry") as mock_save:
                with patch(
                    "tools.gimo_server.routers.ops.repo_router.RepoOverrideService.set_human_override",
                    return_value={"etag": '"etag1"', "expires_at": "2099-01-01T00:00:00Z"},
                ):
                    response = client.post(f"/ops/repos/select?path={repo}")
                    assert response.status_code == 200
                    mock_save.assert_called_once()
                    assert response.json()["active_repo"] == str(repo.resolve())


def test_select_repo_actions_forbidden(tmp_path):
    def override_actions():
        return AuthContext(token="actions-token", role="actions")

    app.dependency_overrides[verify_token] = override_actions
    client = TestClient(app, raise_server_exceptions=False)
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        response = client.post(f"/ops/repos/select?path={repo}")
        assert response.status_code == 403
        assert response.json()["detail"] == "admin role or higher required"
    app.dependency_overrides.clear()


def test_select_repo_etag_mismatch_returns_409(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        with patch("tools.gimo_server.routers.ops.repo_router.load_repo_registry", return_value={"repos": []}):
            with patch("tools.gimo_server.routers.ops.repo_router.RepoOverrideService.set_human_override", side_effect=ValueError("OVERRIDE_ETAG_MISMATCH")):
                response = client.post(
                    f"/ops/repos/select?path={repo}",
                    headers={"If-Match": '"bad"'},
                )
                assert response.status_code == 409
                assert response.json()["detail"] == "OVERRIDE_ETAG_MISMATCH"


def test_revoke_repo_override_success(client):
    with patch("tools.gimo_server.routers.ops.repo_router.RepoOverrideService.revoke_human_override", return_value=True):
        response = client.post("/ops/repos/revoke", headers={"If-Match": '"etag1"'})
        assert response.status_code == 200
        assert response.json()["revoked"] is True


def test_revoke_repo_override_etag_mismatch(client):
    with patch("tools.gimo_server.routers.ops.repo_router.RepoOverrideService.revoke_human_override", side_effect=ValueError("OVERRIDE_ETAG_MISMATCH")):
        response = client.post("/ops/repos/revoke", headers={"If-Match": '"bad"'})
        assert response.status_code == 409
        assert response.json()["detail"] == "OVERRIDE_ETAG_MISMATCH"


def test_select_repo_fail_outside(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path / "root"):
        response = client.post(f"/ops/repos/select?path={tmp_path / 'outside'}")
        assert response.status_code == 400


def test_select_repo_fail_not_found(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path):
        response = client.post(f"/ops/repos/select?path={tmp_path / 'nonexistent'}")
        assert response.status_code == 404


def test_select_repo_operator_forbidden(tmp_path):
    def override_operator():
        return AuthContext(token="operator-token", role="operator")

    app.dependency_overrides[verify_token] = override_operator
    client = TestClient(app, raise_server_exceptions=False)
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        response = client.post(f"/ops/repos/select?path={repo}")
        assert response.status_code == 403
    app.dependency_overrides.clear()


def test_get_security_events(client):
    with patch(
        "tools.gimo_server.security.threat_engine.snapshot",
        return_value={"panic_mode": False, "recent_events": []},
    ):
        response = client.get("/ops/security/events")
        assert response.status_code == 200
        assert response.json()["panic_mode"] is False


def test_security_resolve_success(client):
    from tools.gimo_server.security.threat_level import ThreatLevel
    with patch("tools.gimo_server.security.threat_engine") as mock_engine:
        mock_engine.level = ThreatLevel.NOMINAL
        mock_engine.level_label = "NOMINAL"
        with patch("tools.gimo_server.security.save_security_db"):
            response = client.post("/ops/security/resolve?action=clear_all")
            assert response.status_code == 200
            mock_engine.clear_all.assert_called_once()
            data = response.json()
            assert data["action"] == "clear_all"


def test_security_resolve_invalid(client):
    response = client.post("/ops/security/resolve?action=invalid")
    assert response.status_code == 400


def test_get_service_status(client):
    with patch("tools.gimo_server.routers.ops.service_router.SystemService.get_status", return_value="RUNNING"):
        response = client.get("/ops/service/status")
        assert response.status_code == 200
        assert response.json()["status"] == "RUNNING"


def test_service_restart_success(client):
    with patch("tools.gimo_server.routers.ops.service_router.SystemService.restart", return_value=True):
        response = client.post("/ops/service/restart")
        assert response.status_code == 200


def test_service_restart_fail(client):
    with patch("tools.gimo_server.routers.ops.service_router.SystemService.restart", return_value=False):
        response = client.post("/ops/service/restart")
        assert response.status_code == 500


def test_service_stop_success(client):
    with patch("tools.gimo_server.routers.ops.service_router.SystemService.stop", return_value=True):
        response = client.post("/ops/service/stop")
        assert response.status_code == 200


def test_service_stop_fail(client):
    with patch("tools.gimo_server.routers.ops.service_router.SystemService.stop", return_value=False):
        response = client.post("/ops/service/stop")
        assert response.status_code == 500


def test_vitaminize_repo_success(client, tmp_path):
    repo = tmp_path / "v-repo"
    repo.mkdir()
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path):
        with patch(
            "tools.gimo_server.routers.ops.repo_router.RepoService.vitaminize_repo", return_value=["vit"]
        ):
            with patch("tools.gimo_server.routers.ops.repo_router.load_repo_registry", return_value={}):
                with patch("tools.gimo_server.routers.ops.repo_router.save_repo_registry"):
                    response = client.post(f"/ops/repos/vitaminize?path={repo}")
                    assert response.status_code == 200


def test_vitaminize_repo_fail_outside(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path / "root"):
        response = client.post(f"/ops/repos/vitaminize?path={tmp_path / 'outside'}")
        assert response.status_code == 400


def test_vitaminize_repo_fail_not_found(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.repo_router.REPO_ROOT_DIR", tmp_path):
        response = client.post(f"/ops/repos/vitaminize?path={tmp_path / 'none'}")
        assert response.status_code == 404


def test_get_tree_success(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.file_router.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routers.ops.file_router.validate_path", return_value=tmp_path):
            with patch(
                "tools.gimo_server.routers.ops.file_router.RepoService.walk_tree", return_value=["f1.py"]
            ):
                with patch("tools.gimo_server.routers.ops.file_router.ALLOWLIST_REQUIRE", False):
                    response = client.get("/ops/files/tree?path=.")
                    assert response.status_code == 200
                    assert "f1.py" in response.json()["files"]


def test_get_tree_allowlist_branch(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.file_router.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routers.ops.file_router.validate_path", return_value=tmp_path):
            with patch("tools.gimo_server.routers.ops.file_router.ALLOWLIST_REQUIRE", True):
                with patch(
                    "tools.gimo_server.routers.ops.file_router.get_allowed_paths",
                    return_value={tmp_path / "allowed.txt"},
                ):
                    response = client.get("/ops/files/tree?path=.")
                    assert response.status_code == 200
                    assert "allowed.txt" in response.json()["files"]


def test_get_tree_not_dir(client, tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("ok")
    with patch("tools.gimo_server.routers.ops.file_router.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routers.ops.file_router.validate_path", return_value=f):
            response = client.get("/ops/files/tree?path=f.txt")
            assert response.status_code == 400


def test_get_file_success(client, tmp_path):
    f = tmp_path / "test.py"
    f.write_text("content")
    with patch("tools.gimo_server.routers.ops.file_router.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routers.ops.file_router.validate_path", return_value=f):
            with patch(
                "tools.gimo_server.routers.ops.file_router.FileService.get_file_content",
                return_value=("content", "hash"),
            ):
                response = client.get("/ops/files/content?path=test.py")
                assert response.status_code == 200
                assert response.text == "content"


def test_get_file_too_large(client, tmp_path):
    f = tmp_path / "large.py"
    f.write_text("a")
    with patch("tools.gimo_server.routers.ops.file_router.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routers.ops.file_router.validate_path", return_value=f):
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 10 * 1024 * 1024
                mock_stat.return_value.st_mode = 0o100644  # Regular file
                response = client.get("/ops/files/content?path=large.py")
                assert response.status_code == 413


def test_get_file_not_file(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.file_router.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routers.ops.file_router.validate_path", return_value=tmp_path):
            response = client.get("/ops/files/content?path=.")
            assert response.status_code == 400


def test_get_file_exception(client, tmp_path):
    f = tmp_path / "test.py"
    f.write_text("ok")
    with patch("tools.gimo_server.routers.ops.file_router.get_active_repo_dir", return_value=tmp_path):
        with patch("tools.gimo_server.routers.ops.file_router.validate_path", return_value=f):
            with patch(
                "tools.gimo_server.routers.ops.file_router.FileService.get_file_content",
                side_effect=Exception("oops"),
            ):
                response = client.get("/ops/files/content?path=test.py")
                assert response.status_code == 500


def test_search(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.file_router.get_active_repo_dir", return_value=tmp_path):
        with patch(
            "tools.gimo_server.routers.ops.file_router.RepoService.perform_search",
            return_value=[{"file": "a.py"}],
        ):
            response = client.get("/ops/files/search?q=query")
            assert response.status_code == 200
            assert len(response.json()["results"]) == 1


def test_diff_success(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.file_router.get_active_repo_dir", return_value=tmp_path):
        with patch(
            "tools.gimo_server.services.git_service.GitService.get_diff",
            return_value="diff data",
        ):
            response = client.get("/ops/files/diff")
            assert response.status_code == 200
            assert response.text == "diff data"


def test_diff_truncated(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.file_router.get_active_repo_dir", return_value=tmp_path):
        # Use a string that won't be redacted but IS long
        long_diff = "line\n" * 100
        with patch(
            "tools.gimo_server.services.git_service.GitService.get_diff",
            return_value=long_diff,
        ):
            with patch("tools.gimo_server.config.MAX_BYTES", 10):
                response = client.get("/ops/files/diff")
                assert response.status_code == 200
                assert "TRUNCATED" in response.text


def test_diff_error(client, tmp_path):
    with patch("tools.gimo_server.routers.ops.file_router.get_active_repo_dir", return_value=tmp_path):
        with patch(
            "tools.gimo_server.services.git_service.GitService.get_diff",
            side_effect=Exception("git fail"),
        ):
            response = client.get("/ops/files/diff")
            assert response.status_code == 400
            assert "git fail" in response.json()["detail"]
