"""R17 Cluster E.2 — /ops/providers/diagnostics tests."""

from __future__ import annotations

import pytest

from tools.gimo_server.models import ProviderDiagnosticEntry, ProviderDiagnosticReport


@pytest.fixture
def _stub_report(monkeypatch):
    from tools.gimo_server.services.providers import provider_diagnostics_service as svc_mod

    async def _fake_report():
        return ProviderDiagnosticReport(
            entries=[
                ProviderDiagnosticEntry(
                    provider_id="openai",
                    reachable=True,
                    auth_status="ok",
                    method="api_key",
                    latency_ms=12.3,
                ),
                ProviderDiagnosticEntry(
                    provider_id="claude-account",
                    reachable=False,
                    auth_status="missing",
                ),
            ],
            total=2,
            healthy=1,
        )

    monkeypatch.setattr(svc_mod.ProviderDiagnosticsService, "report", classmethod(lambda cls: _fake_report()))


def test_provider_diagnostics_endpoint_returns_report(test_client, valid_token, _stub_report):
    resp = test_client.get(
        "/ops/providers/diagnostics",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["healthy"] == 1
    assert len(data["entries"]) == 2
    first = data["entries"][0]
    assert first["provider_id"] == "openai"
    assert first["reachable"] is True
    assert first["auth_status"] == "ok"


def test_provider_diagnostics_endpoint_requires_auth(test_client):
    resp = test_client.get("/ops/providers/diagnostics")
    assert resp.status_code in (401, 403)
