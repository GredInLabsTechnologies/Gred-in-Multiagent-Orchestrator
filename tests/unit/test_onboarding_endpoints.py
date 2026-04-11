"""Endpoint-level tests for zero-ADB onboarding + model catalog routes.

Tests the full HTTP contract that the Android OnboardingClient consumes:
  - POST /ops/mesh/onboard/code   (admin auth)
  - POST /ops/mesh/onboard/redeem (NO auth)
  - GET  /ops/mesh/onboard/discover (NO auth)
  - GET  /ops/mesh/models          (operator auth)
  - GET  /ops/mesh/models/{id}     (operator auth)
  - GET  /ops/mesh/models/{id}/download (operator auth)
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from tests.conftest import DEFAULT_TEST_TOKEN


@pytest.fixture(autouse=True)
def _enable_mesh(test_client, monkeypatch):
    """Ensure mesh is enabled for all tests in this module."""
    from tools.gimo_server.services.ops_service import OpsService
    from tools.gimo_server.ops_models import OpsConfig

    original = OpsService.get_config
    def _patched():
        cfg = original()
        return cfg.model_copy(update={"mesh_enabled": True})
    monkeypatch.setattr(OpsService, "get_config", staticmethod(_patched))


@pytest.fixture()
def _isolated_onboard(monkeypatch):
    """Isolate onboarding service to a temp dir."""
    from tools.gimo_server.services.mesh import onboarding as mod
    d = Path(tempfile.mkdtemp(prefix="ep_onboard_"))
    monkeypatch.setattr(mod, "_BASE", d / "codes")
    monkeypatch.setattr(mod, "_LOCK", d / ".lock")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def _isolated_models(monkeypatch):
    """Isolate model catalog to a temp dir with a fake .gguf."""
    from tools.gimo_server.services.mesh import model_catalog as mod
    d = Path(tempfile.mkdtemp(prefix="ep_models_"))
    models = d / "models"
    models.mkdir()
    # Create a small fake model
    fake = models / "test-model.gguf"
    fake.write_bytes(b"GGUF_FAKE_CONTENT_FOR_TESTING")
    monkeypatch.setattr(mod, "_MODELS_DIR", models)
    # Clear any cached catalog instance
    from tools.gimo_server.main import app
    if hasattr(app.state, "model_catalog"):
        delattr(app.state, "model_catalog")
    yield d
    shutil.rmtree(d, ignore_errors=True)


AUTH = {"Authorization": f"Bearer {DEFAULT_TEST_TOKEN}"}


# ═══════════════════════════════════════════════════════════════
# POST /ops/mesh/onboard/discover — NO auth
# ═══════════════════════════════════════════════════════════════

class TestDiscover:
    def test_discover_returns_core_info(self, test_client):
        r = test_client.get("/ops/mesh/onboard/discover")
        assert r.status_code == 200
        data = r.json()
        assert "mesh_enabled" in data
        assert "version" in data
        assert "core_id" in data

    def test_discover_no_auth_required(self, test_client):
        """Endpoint must work without any Authorization header."""
        r = test_client.get("/ops/mesh/onboard/discover")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════
# POST /ops/mesh/onboard/code — admin auth
# ═══════════════════════════════════════════════════════════════

class TestGenerateCode:
    def test_generate_code_success(self, test_client, _isolated_onboard):
        r = test_client.post(
            "/ops/mesh/onboard/code",
            json={"workspace_id": "default"},
            headers=AUTH,
        )
        assert r.status_code == 200
        data = r.json()
        assert "code" in data
        assert len(data["code"]) == 6
        assert data["code"].isdigit()
        assert data["workspace_id"] == "default"
        assert "expires_at" in data

    def test_generate_code_requires_auth(self, test_client, _isolated_onboard):
        r = test_client.post(
            "/ops/mesh/onboard/code",
            json={"workspace_id": "default"},
        )
        assert r.status_code == 401

    def test_generate_code_nonexistent_workspace(self, test_client, _isolated_onboard):
        r = test_client.post(
            "/ops/mesh/onboard/code",
            json={"workspace_id": "ws-does-not-exist"},
            headers=AUTH,
        )
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════
# POST /ops/mesh/onboard/redeem — NO auth
# ═══════════════════════════════════════════════════════════════

class TestRedeemCode:
    def _generate_code(self, test_client) -> str:
        r = test_client.post(
            "/ops/mesh/onboard/code",
            json={"workspace_id": "default"},
            headers=AUTH,
        )
        return r.json()["code"]

    def test_redeem_success(self, test_client, _isolated_onboard):
        code = self._generate_code(test_client)
        r = test_client.post(
            "/ops/mesh/onboard/redeem",
            json={
                "code": code,
                "device_id": "test-device-ep",
                "name": "Test Device",
                "device_mode": "inference",
                "device_class": "smartphone",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["device_id"] == "test-device-ep"
        assert len(data["bearer_token"]) > 0
        assert data["workspace_id"] == "default"
        assert data["status"] == "pending_approval"

    def test_redeem_no_auth_required(self, test_client, _isolated_onboard):
        """Redeem must work without Authorization header."""
        code = self._generate_code(test_client)
        r = test_client.post(
            "/ops/mesh/onboard/redeem",
            json={
                "code": code,
                "device_id": "test-noauth",
                "name": "NoAuth",
            },
        )
        assert r.status_code == 200

    def test_redeem_invalid_code(self, test_client, _isolated_onboard):
        r = test_client.post(
            "/ops/mesh/onboard/redeem",
            json={"code": "000000", "device_id": "dev-bad"},
        )
        assert r.status_code == 403

    def test_redeem_bad_format(self, test_client, _isolated_onboard):
        r = test_client.post(
            "/ops/mesh/onboard/redeem",
            json={"code": "abc", "device_id": "dev-bad"},
        )
        assert r.status_code == 403

    def test_redeem_invalid_device_id(self, test_client, _isolated_onboard):
        code = self._generate_code(test_client)
        r = test_client.post(
            "/ops/mesh/onboard/redeem",
            json={"code": code, "device_id": "../etc/passwd"},
        )
        assert r.status_code == 400

    def test_redeem_code_single_use(self, test_client, _isolated_onboard):
        code = self._generate_code(test_client)
        # First use succeeds
        r1 = test_client.post(
            "/ops/mesh/onboard/redeem",
            json={"code": code, "device_id": "dev-first-ep"},
        )
        assert r1.status_code == 200
        # Second use fails
        r2 = test_client.post(
            "/ops/mesh/onboard/redeem",
            json={"code": code, "device_id": "dev-second-ep"},
        )
        assert r2.status_code == 403


# ═══════════════════════════════════════════════════════════════
# Device auth with bearer_token from onboarding
# ═══════════════════════════════════════════════════════════════

class TestDeviceAuth:
    def test_device_can_access_models_with_bearer_token(
        self, test_client, _isolated_onboard, _isolated_models
    ):
        """After onboarding, device uses bearer_token to access model catalog."""
        # Generate and redeem code
        code_r = test_client.post(
            "/ops/mesh/onboard/code",
            json={"workspace_id": "default"},
            headers=AUTH,
        )
        code = code_r.json()["code"]
        redeem_r = test_client.post(
            "/ops/mesh/onboard/redeem",
            json={"code": code, "device_id": "dev-auth-test", "name": "AuthTest"},
        )
        bearer = redeem_r.json()["bearer_token"]

        # Use bearer_token to access model catalog
        r = test_client.get(
            "/ops/mesh/models",
            headers={"Authorization": f"Bearer {bearer}"},
        )
        assert r.status_code == 200
        models = r.json()
        assert isinstance(models, list)
        assert len(models) >= 1
        assert models[0]["model_id"] == "test-model"


# ═══════════════════════════════════════════════════════════════
# GET /ops/mesh/models — operator auth
# ═══════════════════════════════════════════════════════════════

class TestModelCatalog:
    def test_list_models(self, test_client, _isolated_models):
        r = test_client.get("/ops/mesh/models", headers=AUTH)
        assert r.status_code == 200
        models = r.json()
        assert isinstance(models, list)
        assert len(models) >= 1
        m = models[0]
        assert "model_id" in m
        assert "filename" in m
        assert "size_bytes" in m
        assert "sha256" in m

    def test_list_models_requires_auth(self, test_client, _isolated_models):
        r = test_client.get("/ops/mesh/models")
        assert r.status_code == 401

    def test_get_model_info(self, test_client, _isolated_models):
        r = test_client.get("/ops/mesh/models/test-model", headers=AUTH)
        assert r.status_code == 200
        m = r.json()
        assert m["model_id"] == "test-model"
        assert m["filename"] == "test-model.gguf"

    def test_get_model_not_found(self, test_client, _isolated_models):
        r = test_client.get("/ops/mesh/models/nonexistent", headers=AUTH)
        assert r.status_code == 404

    def test_download_model(self, test_client, _isolated_models):
        r = test_client.get("/ops/mesh/models/test-model/download", headers=AUTH)
        assert r.status_code == 200
        assert r.content == b"GGUF_FAKE_CONTENT_FOR_TESTING"
        assert "content-length" in r.headers
        assert r.headers.get("content-type") == "application/octet-stream"

    def test_download_model_range_resume(self, test_client, _isolated_models):
        """Range header returns partial content for download resume."""
        r = test_client.get(
            "/ops/mesh/models/test-model/download",
            headers={**AUTH, "Range": "bytes=5-"},
        )
        assert r.status_code == 206
        assert r.content == b"GGUF_FAKE_CONTENT_FOR_TESTING"[5:]
        assert "content-range" in r.headers

    def test_download_not_found(self, test_client, _isolated_models):
        r = test_client.get("/ops/mesh/models/ghost/download", headers=AUTH)
        assert r.status_code == 404
