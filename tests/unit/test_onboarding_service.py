"""Unit tests for OnboardingService — zero-ADB device enrollment."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import pytest

from tools.gimo_server.models.mesh import DeviceMode
from tools.gimo_server.services.mesh import onboarding as onboard_mod
from tools.gimo_server.services.mesh.onboarding import OnboardingService


@pytest.fixture()
def tmp_dir() -> Generator[Path, None, None]:
    d = Path(tempfile.mkdtemp(prefix="onboard_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def svc(tmp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> OnboardingService:
    monkeypatch.setattr(onboard_mod, "_BASE", tmp_dir / "onboard_codes")
    monkeypatch.setattr(onboard_mod, "_LOCK", tmp_dir / ".onboard.lock")
    # Also patch workspace_service and registry for isolation
    from tools.gimo_server.services.mesh import workspace_service as ws_mod
    from tools.gimo_server.services.mesh import registry as registry_mod
    from tools.gimo_server.services.mesh.registry import MeshRegistry

    monkeypatch.setattr(ws_mod, "_BASE", tmp_dir / "mesh" / "workspaces")
    monkeypatch.setattr(ws_mod, "_LOCK", tmp_dir / "mesh" / ".workspaces.lock")
    monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", tmp_dir)
    monkeypatch.setattr(MeshRegistry, "MESH_DIR", tmp_dir / "mesh")
    monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", tmp_dir / "mesh" / "devices")
    monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", tmp_dir / "mesh" / "tokens")
    monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", tmp_dir / "mesh" / "thermal_events.jsonl")
    monkeypatch.setattr(MeshRegistry, "LOCK_FILE", tmp_dir / "mesh" / ".mesh.lock")
    return OnboardingService()


# ═══════════════════════════════════════════════════════════════
# Code generation
# ═══════════════════════════════════════════════════════════════

class TestCodeGeneration:
    def test_create_code_returns_6_digits(self, svc: OnboardingService):
        oc = svc.create_code()
        assert len(oc.code) == 6
        assert oc.code.isdigit()

    def test_create_code_default_workspace(self, svc: OnboardingService):
        oc = svc.create_code()
        assert oc.workspace_id == "default"

    def test_create_code_custom_workspace(self, svc: OnboardingService):
        oc = svc.create_code(workspace_id="ws-custom")
        assert oc.workspace_id == "ws-custom"

    def test_create_code_not_used(self, svc: OnboardingService):
        oc = svc.create_code()
        assert oc.used is False

    def test_create_code_has_expiry(self, svc: OnboardingService):
        oc = svc.create_code()
        assert oc.expires_at > datetime.now(timezone.utc)
        # Should expire in ~5 minutes
        delta = (oc.expires_at - datetime.now(timezone.utc)).total_seconds()
        assert 240 < delta < 310  # 4-5.1 minutes

    def test_codes_are_unique(self, svc: OnboardingService):
        codes = {svc.create_code().code for _ in range(20)}
        # With 1M possible codes and 20 samples, collision is extremely unlikely
        assert len(codes) >= 19


# ═══════════════════════════════════════════════════════════════
# Code redemption
# ═══════════════════════════════════════════════════════════════

class TestCodeRedemption:
    def test_redeem_valid_code(self, svc: OnboardingService):
        oc = svc.create_code()
        result = svc.redeem_code(oc.code, "dev-new", name="NewDevice")
        assert result is not None
        assert result.device_id == "dev-new"
        assert result.bearer_token != ""
        assert result.workspace_id == "default"
        assert result.status == "pending_approval"

    def test_redeem_returns_bearer_token(self, svc: OnboardingService):
        oc = svc.create_code()
        result = svc.redeem_code(oc.code, "dev-token")
        # bearer_token is the device_secret from MeshDeviceInfo
        assert len(result.bearer_token) > 0

    def test_code_is_single_use(self, svc: OnboardingService):
        oc = svc.create_code()
        svc.redeem_code(oc.code, "dev-first")
        result = svc.redeem_code(oc.code, "dev-second")
        assert result is None

    def test_invalid_code_rejected(self, svc: OnboardingService):
        result = svc.redeem_code("999999", "dev-bad")
        assert result is None

    def test_non_numeric_code_rejected(self, svc: OnboardingService):
        result = svc.redeem_code("abcdef", "dev-bad")
        assert result is None

    def test_short_code_rejected(self, svc: OnboardingService):
        result = svc.redeem_code("123", "dev-bad")
        assert result is None

    def test_empty_code_rejected(self, svc: OnboardingService):
        result = svc.redeem_code("", "dev-bad")
        assert result is None

    def test_expired_code_rejected(self, svc: OnboardingService, monkeypatch):
        oc = svc.create_code()
        # Manually expire the code
        oc.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        svc._save_code(oc)

        result = svc.redeem_code(oc.code, "dev-late")
        assert result is None

    def test_already_enrolled_device_returns_existing(self, svc: OnboardingService):
        """If device is already enrolled, return its existing secret."""
        oc1 = svc.create_code()
        result1 = svc.redeem_code(oc1.code, "dev-dup")
        assert result1 is not None

        oc2 = svc.create_code()
        result2 = svc.redeem_code(oc2.code, "dev-dup")
        assert result2 is not None
        assert result2.bearer_token == result1.bearer_token

    def test_redeem_joins_workspace(self, svc: OnboardingService):
        """Device should be added as member of the workspace."""
        from tools.gimo_server.services.mesh.workspace_service import WorkspaceService
        ws_svc = WorkspaceService()

        oc = svc.create_code()
        result = svc.redeem_code(oc.code, "dev-ws")
        assert result is not None

        member = ws_svc.get_member("default", "dev-ws")
        assert member is not None

    def test_redeem_custom_workspace(self, svc: OnboardingService):
        """Device joins the specified workspace, not just default."""
        from tools.gimo_server.services.mesh.workspace_service import WorkspaceService
        ws_svc = WorkspaceService()
        ws = ws_svc.create_workspace(name="CustomWS")

        oc = svc.create_code(workspace_id=ws.workspace_id)
        result = svc.redeem_code(oc.code, "dev-custom")
        assert result is not None
        assert result.workspace_id == ws.workspace_id

        member = ws_svc.get_member(ws.workspace_id, "dev-custom")
        assert member is not None


# ═══════════════════════════════════════════════════════════════
# Purge expired codes
# ═══════════════════════════════════════════════════════════════

class TestPurgeExpired:
    def test_purge_removes_expired(self, svc: OnboardingService):
        oc = svc.create_code()
        # Manually expire
        oc.expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        svc._save_code(oc)

        purged = svc._purge_expired()
        assert purged >= 1

    def test_purge_removes_used(self, svc: OnboardingService):
        oc = svc.create_code()
        svc.redeem_code(oc.code, "dev-purge")
        # Code is now used
        purged = svc._purge_expired()
        assert purged >= 1
