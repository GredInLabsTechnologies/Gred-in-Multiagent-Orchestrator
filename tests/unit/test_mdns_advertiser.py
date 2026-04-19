"""Unit tests for mDNS advertiser + HMAC signer + QR payload."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools.gimo_server.services.mesh.hmac_signer import sign_payload, verify_payload


# ═══════════════════════════════════════════════════════════════
# HMAC Signer
# ═══════════════════════════════════════════════════════════════

class TestHmacSigner:
    def test_sign_returns_16_hex_chars(self):
        sig = sign_payload("my-token", "some-payload")
        assert len(sig) == 32
        assert all(c in "0123456789abcdef" for c in sig)

    def test_sign_deterministic(self):
        s1 = sign_payload("tok", "data")
        s2 = sign_payload("tok", "data")
        assert s1 == s2

    def test_sign_differs_with_different_token(self):
        s1 = sign_payload("token-a", "data")
        s2 = sign_payload("token-b", "data")
        assert s1 != s2

    def test_sign_differs_with_different_payload(self):
        s1 = sign_payload("tok", "payload-a")
        s2 = sign_payload("tok", "payload-b")
        assert s1 != s2

    def test_verify_valid(self):
        sig = sign_payload("tok", "data")
        assert verify_payload("tok", "data", sig) is True

    def test_verify_invalid_sig(self):
        assert verify_payload("tok", "data", "0000000000000000") is False

    def test_verify_wrong_token(self):
        sig = sign_payload("tok-a", "data")
        assert verify_payload("tok-b", "data", sig) is False

    def test_verify_wrong_payload(self):
        sig = sign_payload("tok", "data-a")
        assert verify_payload("tok", "data-b", sig) is False

    def test_empty_token_still_works(self):
        sig = sign_payload("", "data")
        assert len(sig) == 32
        assert verify_payload("", "data", sig) is True


# ═══════════════════════════════════════════════════════════════
# mDNS Advertiser
# ═══════════════════════════════════════════════════════════════

class TestMdnsAdvertiser:
    def test_start_registers_service(self):
        from tools.gimo_server.services.mesh.mdns_advertiser import MdnsAdvertiser

        with patch("tools.gimo_server.services.mesh.mdns_advertiser.Zeroconf", create=True) as MockZC, \
             patch("tools.gimo_server.services.mesh.mdns_advertiser.ServiceInfo", create=True) as MockSI:
            # Patch the import inside start()
            import tools.gimo_server.services.mesh.mdns_advertiser as mod
            mock_zc_cls = MagicMock()
            mock_si_cls = MagicMock()

            with patch.dict("sys.modules", {"zeroconf": MagicMock(
                Zeroconf=mock_zc_cls, ServiceInfo=mock_si_cls
            )}):
                adv = MdnsAdvertiser(port=9325, token="test-token")
                adv.start()

                assert adv.is_running is True
                mock_zc_cls.return_value.register_service.assert_called_once()

    def test_stop_without_start_is_noop(self):
        from tools.gimo_server.services.mesh.mdns_advertiser import MdnsAdvertiser
        adv = MdnsAdvertiser(port=9325)
        adv.stop()  # Should not raise
        assert adv.is_running is False

    def test_start_idempotent(self):
        from tools.gimo_server.services.mesh.mdns_advertiser import MdnsAdvertiser
        mock_zc_cls = MagicMock()
        mock_si_cls = MagicMock()

        with patch.dict("sys.modules", {"zeroconf": MagicMock(
            Zeroconf=mock_zc_cls, ServiceInfo=mock_si_cls
        )}):
            adv = MdnsAdvertiser(port=9325, token="tok")
            adv.start()
            adv.start()  # Second call should be no-op
            assert mock_zc_cls.call_count == 1

    def test_start_without_zeroconf_installed(self):
        from tools.gimo_server.services.mesh.mdns_advertiser import MdnsAdvertiser

        with patch.dict("sys.modules", {"zeroconf": None}):
            adv = MdnsAdvertiser(port=9325)
            # start() should handle ImportError gracefully
            # We need to force the import to fail
            original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

            def mock_import(name, *args, **kwargs):
                if name == "zeroconf":
                    raise ImportError("no zeroconf")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                adv.start()
                assert adv.is_running is False

    def test_txt_record_includes_hmac(self):
        from tools.gimo_server.services.mesh.mdns_advertiser import MdnsAdvertiser
        mock_zc_cls = MagicMock()
        mock_si_cls = MagicMock()

        with patch.dict("sys.modules", {"zeroconf": MagicMock(
            Zeroconf=mock_zc_cls, ServiceInfo=mock_si_cls
        )}):
            adv = MdnsAdvertiser(port=9325, token="secret-token")
            adv.start()

            # Check ServiceInfo was called with properties containing hmac
            call_kwargs = mock_si_cls.call_args
            props = call_kwargs.kwargs.get("properties") or call_kwargs[1].get("properties")
            assert "hmac" in props
            assert len(props["hmac"]) == 32
            assert props["mesh"] == "true"
            assert props["version"] == "1.0.0"

    def test_txt_record_includes_runtime_version(self):
        """Plan 2026-04-16 Change 5: runtime_version must be published."""
        from tools.gimo_server.services.mesh.mdns_advertiser import MdnsAdvertiser
        mock_zc_cls = MagicMock()
        mock_si_cls = MagicMock()

        with patch.dict("sys.modules", {"zeroconf": MagicMock(
            Zeroconf=mock_zc_cls, ServiceInfo=mock_si_cls
        )}):
            adv = MdnsAdvertiser(
                port=9325, token="t", runtime_version="0.1.0-test",
            )
            adv.start()
            props = mock_si_cls.call_args.kwargs.get("properties") or {}
            assert props.get("runtime_version") == "0.1.0-test"

    def test_hmac_covers_runtime_version(self):
        """Signing the same hostname with different runtime_versions produces different HMACs."""
        from tools.gimo_server.services.mesh.mdns_advertiser import MdnsAdvertiser

        adv_a = MdnsAdvertiser(port=9325, token="tok", runtime_version="0.1.0")
        adv_b = MdnsAdvertiser(port=9325, token="tok", runtime_version="0.2.0")
        props_a = adv_a._build_properties("hostA")
        props_b = adv_b._build_properties("hostA")
        assert props_a["hmac"] != props_b["hmac"]

    def test_update_signals_changes_runtime_version(self):
        """update_signals(runtime_version=...) rewrites internal state."""
        from tools.gimo_server.services.mesh.mdns_advertiser import MdnsAdvertiser
        adv = MdnsAdvertiser(port=9325, token="t", runtime_version="0.1.0")
        # Not started — still updates internal state
        adv.update_signals(runtime_version="0.2.0")
        assert adv._runtime_version == "0.2.0"


# ═══════════════════════════════════════════════════════════════
# QR Payload in onboard/code endpoint
# ═══════════════════════════════════════════════════════════════

class TestQrPayload:
    def test_onboard_code_includes_qr_payload(self, test_client, _isolated_onboard):
        from tests.conftest import DEFAULT_TEST_TOKEN
        r = test_client.post(
            "/ops/mesh/onboard/code",
            json={"workspace_id": "default"},
            headers={"Authorization": f"Bearer {DEFAULT_TEST_TOKEN}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "qr_payload" in data
        assert data["qr_payload"].startswith("http://")

    def test_qr_payload_contains_code(self, test_client, _isolated_onboard):
        from tests.conftest import DEFAULT_TEST_TOKEN
        r = test_client.post(
            "/ops/mesh/onboard/code",
            json={"workspace_id": "default"},
            headers={"Authorization": f"Bearer {DEFAULT_TEST_TOKEN}"},
        )
        data = r.json()
        code = data["code"]
        assert f"/{code}" in data["qr_payload"]

    def test_qr_payload_contains_sig(self, test_client, _isolated_onboard):
        from tests.conftest import DEFAULT_TEST_TOKEN
        r = test_client.post(
            "/ops/mesh/onboard/code",
            json={"workspace_id": "default"},
            headers={"Authorization": f"Bearer {DEFAULT_TEST_TOKEN}"},
        )
        data = r.json()
        assert "?sig=" in data["qr_payload"]
        # Extract sig and verify it's 16 hex chars
        sig = data["qr_payload"].split("?sig=")[1]
        assert len(sig) == 32
        assert all(c in "0123456789abcdef" for c in sig)

    def test_qr_sig_verifiable(self, test_client, _isolated_onboard):
        """The HMAC sig in the QR payload must be verifiable with the token."""
        import os
        from tests.conftest import DEFAULT_TEST_TOKEN
        r = test_client.post(
            "/ops/mesh/onboard/code",
            json={"workspace_id": "default"},
            headers={"Authorization": f"Bearer {DEFAULT_TEST_TOKEN}"},
        )
        data = r.json()
        qr = data["qr_payload"]  # http://ip:port/ops/mesh/onboard/code/install?sig=xxxx
        # The sig is computed over "ip:port/code" — extract from the URL
        # URL format: http://IP:PORT/ops/mesh/onboard/CODE/install?sig=XXXX
        import re
        m = re.search(r"http://([^/]+)/ops/mesh/onboard/(\d{6})/install\?sig=(\w+)", qr)
        assert m, f"QR payload format unexpected: {qr}"
        host_port = m.group(1)
        qr_code = m.group(2)
        sig = m.group(3)
        payload_part = f"{host_port}/{qr_code}"
        # Verify — the token used is ORCH_TOKEN
        token = os.environ.get("ORCH_TOKEN", DEFAULT_TEST_TOKEN)
        assert verify_payload(token, payload_part, sig) is True


# ═══════════════════════════════════════════════════════════════
# Fixtures (reused from test_onboarding_endpoints.py)
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _enable_mesh(test_client, monkeypatch):
    from tools.gimo_server.services.ops import OpsService
    original = OpsService.get_config

    def _patched():
        cfg = original()
        return cfg.model_copy(update={"mesh_enabled": True})
    monkeypatch.setattr(OpsService, "get_config", staticmethod(_patched))


@pytest.fixture()
def _isolated_onboard(monkeypatch):
    import shutil
    import tempfile
    from pathlib import Path
    from tools.gimo_server.services.mesh import onboarding as mod
    d = Path(tempfile.mkdtemp(prefix="qr_test_"))
    monkeypatch.setattr(mod, "_BASE", d / "codes")
    monkeypatch.setattr(mod, "_LOCK", d / ".lock")
    yield d
    shutil.rmtree(d, ignore_errors=True)
