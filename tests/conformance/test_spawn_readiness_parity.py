"""Spawn readiness parity (R20-003).

Asserts that an unauth provider cannot produce a ghost spawn UUID.
The assertion is made at the ``SubAgentManager._require_provider_readiness``
chokepoint — the same function both HTTP and MCP spawn paths traverse.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest


@dataclass
class _FakeDiag:
    provider_id: str
    reachable: bool = True
    auth_status: str = "missing"
    latency_ms: int = 1
    details: dict = None


@pytest.mark.asyncio
async def test_unauth_provider_fails_readiness(live_backend):
    from tools.gimo_server.services.sub_agent_manager import SubAgentManager
    from tools.gimo_server.services.providers import provider_diagnostics_service as pds

    async def fake_probe(cls_or_self, provider_id: str, *args, **kwargs):
        return _FakeDiag(provider_id=provider_id, reachable=True, auth_status="missing", details={})

    with patch.object(pds.ProviderDiagnosticsService, "_probe_one", classmethod(fake_probe)):
        with pytest.raises(RuntimeError) as exc:
            await SubAgentManager._require_provider_readiness("openai")
        msg = str(exc.value)
        assert msg.startswith("PROVIDER_NOT_READY:openai:")
        # Critical: no UUID in the error; this is a structured failure.
        assert "auth_" in msg
