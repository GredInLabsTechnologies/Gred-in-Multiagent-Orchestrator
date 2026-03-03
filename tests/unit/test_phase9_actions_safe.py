from __future__ import annotations

from tools.gimo_server.main import app
from tools.gimo_server.security import verify_token
from tools.gimo_server.security.auth import AuthContext
from tools.gimo_server.security import rate_limit as rate_limit_module


def _override_admin() -> AuthContext:
    return AuthContext(token="test-token", role="admin")


def test_phase9_filtered_openapi_exposes_only_allowed_contract(test_client):
    app.dependency_overrides[verify_token] = _override_admin
    try:
        res = test_client.get("/ops/openapi.json", headers={"Authorization": "Bearer test-token"})
        assert res.status_code == 200
        payload = res.json()
        paths = payload.get("paths") or {}

        assert set(paths.keys()) == {
            "/ops/drafts",
            "/ops/drafts/{draft_id}/approve",
            "/ops/runs/{run_id}",
            "/ops/runs/{run_id}/preview",
            "/ui/repos",
            "/ui/repos/active",
            "/ui/repos/select",
        }

        assert set(paths["/ops/drafts"].keys()) == {"post"}
        assert set(paths["/ops/drafts/{draft_id}/approve"].keys()) == {"post"}
        assert set(paths["/ops/runs/{run_id}"].keys()) == {"get"}
        assert set(paths["/ops/runs/{run_id}/preview"].keys()) == {"get"}
        assert set(paths["/ui/repos"].keys()) == {"get"}
        assert set(paths["/ui/repos/active"].keys()) == {"get"}
        assert set(paths["/ui/repos/select"].keys()) == {"post"}
    finally:
        app.dependency_overrides.clear()


def test_phase9_filtered_openapi_excludes_internal_and_admin_routes(test_client):
    app.dependency_overrides[verify_token] = _override_admin
    try:
        res = test_client.get("/ops/openapi.json", headers={"Authorization": "Bearer test-token"})
        assert res.status_code == 200
        payload = res.json()
        paths = payload.get("paths") or {}

        forbidden_examples = {
            "/ops/plan",
            "/ops/generate",
            "/ops/provider",
            "/ops/runs",
            "/ui/repos/open",
            "/ui/repos/vitaminize",
            "/ui/service/restart",
            "/ops/workflows/execute",
        }
        for path in forbidden_examples:
            assert path not in paths
    finally:
        app.dependency_overrides.clear()


def test_phase9_actions_payload_limit_returns_413(test_client):
    app.dependency_overrides[verify_token] = _override_admin
    try:
        huge_objective = "A" * (70 * 1024)
        res = test_client.post(
            "/ops/drafts",
            json={"objective": huge_objective, "execution": {"intent_class": "SAFE_REFACTOR"}},
            headers={"Authorization": "Bearer test-token"},
        )
        assert res.status_code == 413
        assert res.json().get("detail") == "Payload too large."
    finally:
        app.dependency_overrides.clear()


def test_phase9_actions_invalid_payload_is_sanitized(test_client):
    app.dependency_overrides[verify_token] = _override_admin
    try:
        # objective must be string; forcing invalid type should trigger RequestValidationError.
        res = test_client.post(
            "/ops/drafts",
            json={"objective": 123, "execution": {"intent_class": "SAFE_REFACTOR"}},
            headers={"Authorization": "Bearer test-token"},
        )
        assert res.status_code == 422
        body = res.json()
        assert body.get("detail") == "Invalid request payload."
        serialized = str(body)
        assert "traceback" not in serialized.lower()
        assert "tools/gimo_server" not in serialized.lower()
    finally:
        app.dependency_overrides.clear()


def test_phase9_actions_rate_limit_applies_to_public_contract(test_client, monkeypatch):
    app.dependency_overrides[verify_token] = _override_admin
    original_limit = rate_limit_module.RATE_LIMIT_PER_MIN
    rate_limit_module.rate_limit_store.clear()
    monkeypatch.setattr(rate_limit_module, "RATE_LIMIT_PER_MIN", 1)
    try:
        first = test_client.get("/ui/repos", headers={"Authorization": "Bearer test-token"})
        assert first.status_code == 200

        second = test_client.get("/ui/repos", headers={"Authorization": "Bearer test-token"})
        assert second.status_code == 429
        assert second.json().get("detail") == "Too many requests"
    finally:
        app.dependency_overrides.clear()
        rate_limit_module.rate_limit_store.clear()
        monkeypatch.setattr(rate_limit_module, "RATE_LIMIT_PER_MIN", original_limit)
