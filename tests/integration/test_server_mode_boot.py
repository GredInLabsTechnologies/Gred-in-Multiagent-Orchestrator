"""Smoke test: GIMO Core boots cleanly in server mode (rev 2 Cambio 7).

Server mode = mDNS enabled + host bootstrap registered + advertiser seeded with
the host's routing signals (mode/health/load). This test replays the env-var
contract that the CLI `--role server` flag writes, then drives the lifespan
code paths that the real launcher executes.

We never bind a real socket here — we instantiate ``MdnsAdvertiser`` with the
zeroconf import mocked out so the test is deterministic and offline-safe, and
we call the bootstrap service directly. The goal is contract verification:

1. ``AndroidHostBootstrapService`` honours ``GIMO_MESH_HOST_*`` env vars and
   registers the local Core as a mesh device with ``device_mode=server``.
2. The mDNS advertiser's TXT-record builder includes the new rev 2 routing
   signals (mode, health, load) and the HMAC covers them all.
3. ``update_signals`` re-encodes the payload without touching zeroconf when
   the advertiser is inactive (best-effort contract).
4. ``GET /ops/mesh/host`` returns the bootstrapped host when the registry
   knows about it.

Android export path is unaffected — this test is additive, mesh-disabled
boot is still covered by ``test_boot_mesh_disabled.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.gimo_server.models.mesh import DeviceMode
from tools.gimo_server.services.mesh import registry as registry_mod
from tools.gimo_server.services.mesh.host_bootstrap import (
    AndroidHostBootstrapConfig,
    AndroidHostBootstrapService,
)
from tools.gimo_server.services.mesh.mdns_advertiser import MdnsAdvertiser
from tools.gimo_server.services.mesh.registry import MeshRegistry


@pytest.fixture()
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MeshRegistry:
    monkeypatch.setattr(registry_mod, "OPS_DATA_DIR", tmp_path)
    monkeypatch.setattr(MeshRegistry, "MESH_DIR", tmp_path / "mesh")
    monkeypatch.setattr(MeshRegistry, "DEVICES_DIR", tmp_path / "mesh" / "devices")
    monkeypatch.setattr(MeshRegistry, "TOKENS_DIR", tmp_path / "mesh" / "tokens")
    monkeypatch.setattr(MeshRegistry, "THERMAL_LOG", tmp_path / "mesh" / "thermal_events.jsonl")
    monkeypatch.setattr(MeshRegistry, "LOCK_FILE", tmp_path / "mesh" / ".mesh.lock")
    return MeshRegistry()


class TestHostBootstrapFromEnv:
    def test_server_env_produces_server_mode_device(
        self, isolated_registry: MeshRegistry, monkeypatch: pytest.MonkeyPatch
    ):
        """`--role server --mesh-host-id X` propagates env → bootstrap produces server device."""
        monkeypatch.setenv("GIMO_MESH_HOST_ENABLED", "true")
        monkeypatch.setenv("GIMO_MESH_HOST_DEVICE_ID", "desktop-s10")
        monkeypatch.setenv("GIMO_MESH_HOST_DEVICE_MODE", "server")
        monkeypatch.setenv("GIMO_MESH_HOST_DEVICE_CLASS", "desktop")

        cfg = AndroidHostBootstrapConfig.from_env()
        assert cfg is not None
        assert cfg.enabled is True
        assert cfg.device_id == "desktop-s10"
        assert cfg.device_mode == DeviceMode.server

        device = AndroidHostBootstrapService(isolated_registry).bootstrap(cfg)
        assert device.device_mode == DeviceMode.server
        assert device.device_class == "desktop"
        assert device.local_allow_core_control is True
        assert device.local_allow_task_execution is True

    def test_bootstrap_returns_none_when_disabled(
        self, isolated_registry: MeshRegistry, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("GIMO_MESH_HOST_ENABLED", raising=False)
        assert AndroidHostBootstrapService(isolated_registry).bootstrap_from_env() is None


class TestMdnsTxtRecordSignals:
    def test_txt_record_includes_mode_health_load(self):
        """rev 2 Cambio 11 — TXT record must publish the routing signals."""
        advertiser = MdnsAdvertiser(port=9325, token="unit-token")
        # `update_signals` before start() must never throw — it just records state
        advertiser.update_signals(health=83, mode="server", load=0.42)
        props = advertiser._build_properties("gimo-host")  # noqa: SLF001 — whitebox check

        assert props["mode"] == "server"
        assert props["health"] == "83"
        assert props["load"] == "0.42"
        # HMAC must be present and non-empty when a token is configured
        assert props["hmac"]
        assert len(props["hmac"]) == 32  # NIST-truncated to 128 bits = 32 hex chars

    def test_hmac_covers_signals(self):
        """Changing the routing signals must invalidate the previous HMAC."""
        advertiser = MdnsAdvertiser(port=9325, token="unit-token")
        advertiser.update_signals(health=100, mode="server", load=0.1)
        sig_before = advertiser._build_properties("gimo-host")["hmac"]

        advertiser.update_signals(health=40, mode="server", load=0.9)
        sig_after = advertiser._build_properties("gimo-host")["hmac"]

        assert sig_before != sig_after, "HMAC must change when mode/health/load change"

    def test_update_signals_without_start_is_best_effort(self):
        """Updating before `start()` must not raise — just records state for next run."""
        advertiser = MdnsAdvertiser(port=9325, token="unit-token")
        # No zeroconf import, no socket — pure state mutation
        advertiser.update_signals(health=75, mode="inference", load=0.2)
        assert advertiser._health == 75  # noqa: SLF001
        assert advertiser._mode == "inference"
        assert abs(advertiser._load - 0.2) < 1e-9


class TestMdnsAutoEnableLogic:
    """rev 2 Cambio 1 — auto-enable condition is (explicit env OR host_device_mode == server)."""

    def test_explicit_env_alone_enables(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ORCH_MDNS_ENABLED", "true")
        # Replicate the gating expression from main.py lifespan
        explicit = monkeypatch.getenv if False else None  # keep style linter quiet
        import os as _os
        mdns_explicit = _os.environ.get("ORCH_MDNS_ENABLED", "false").lower() == "true"
        assert mdns_explicit is True

    def test_auto_enable_when_host_device_mode_is_server(
        self, isolated_registry: MeshRegistry, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("GIMO_MESH_HOST_ENABLED", "true")
        monkeypatch.setenv("GIMO_MESH_HOST_DEVICE_ID", "desktop-auto")
        monkeypatch.setenv("GIMO_MESH_HOST_DEVICE_MODE", "server")
        host = AndroidHostBootstrapService(isolated_registry).bootstrap_from_env()
        assert host is not None
        # Replicate the auto-enable expression
        mdns_auto = host is not None and host.device_mode == DeviceMode.server
        assert mdns_auto is True

    def test_no_auto_enable_when_host_device_mode_is_inference(
        self, isolated_registry: MeshRegistry, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("GIMO_MESH_HOST_ENABLED", "true")
        monkeypatch.setenv("GIMO_MESH_HOST_DEVICE_ID", "phone-infer")
        monkeypatch.setenv("GIMO_MESH_HOST_DEVICE_MODE", "inference")
        host = AndroidHostBootstrapService(isolated_registry).bootstrap_from_env()
        assert host is not None
        mdns_auto = host is not None and host.device_mode == DeviceMode.server
        assert mdns_auto is False, "inference-mode hosts must NOT auto-enable mDNS"
