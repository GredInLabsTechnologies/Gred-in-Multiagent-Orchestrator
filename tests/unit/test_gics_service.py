"""R17 Cluster C: GICS daemon failure visibility.

Verifies that GicsService.start_daemon records a structured GicsStartFailure
on each failure path while preserving the degraded-mode contract (never raises).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from tools.gimo_server.services import gics_service as gics_module
from tools.gimo_server.services.gics_service import GicsService, GicsStartFailure

# The session-scoped autouse `_mock_gics_daemon` fixture in tests/conftest.py
# patches GicsService.start_daemon. We grab the unwrapped function at import
# time so we can invoke the real implementation directly on a fresh instance.
_REAL_START_DAEMON = GicsService.__dict__["start_daemon"]


def _make_service() -> GicsService:
    svc = GicsService()
    return svc


def test_gics_start_daemon_records_cli_not_found(monkeypatch):
    svc = _make_service()
    # Force the CLI path to None to trigger the cli_not_found path.
    svc._cli_path = None

    _REAL_START_DAEMON(svc)

    failure = svc.last_start_failure
    assert isinstance(failure, GicsStartFailure)
    assert failure.reason == "cli_not_found"
    assert "cannot start" in failure.message.lower() or "not found" in failure.message.lower()
    # Contract preserved: no daemon was started.
    assert svc._supervisor is None


def test_gics_start_daemon_records_node_not_found(monkeypatch):
    svc = _make_service()
    # Pretend the CLI exists but Node.js is missing.
    svc._cli_path = "/fake/gics/cli.js"
    monkeypatch.setattr(gics_module.shutil, "which", lambda _name: None)

    _REAL_START_DAEMON(svc)

    failure = svc.last_start_failure
    assert isinstance(failure, GicsStartFailure)
    assert failure.reason == "node_not_found"
    assert "node" in failure.message.lower()
    assert svc._supervisor is None


def test_gics_start_daemon_records_spawn_error(monkeypatch, tmp_path):
    svc = _make_service()
    svc._cli_path = "/fake/gics/cli.js"
    svc._data_path = str(tmp_path / "gics_data")
    monkeypatch.setattr(gics_module.shutil, "which", lambda _name: "/usr/bin/node")

    class _BoomSupervisor:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("supervisor boom")

    monkeypatch.setattr(gics_module, "GICSDaemonSupervisor", _BoomSupervisor)

    # Must NOT raise — degraded mode contract.
    _REAL_START_DAEMON(svc)

    failure = svc.last_start_failure
    assert isinstance(failure, GicsStartFailure)
    assert failure.reason == "spawn_error"
    assert "boom" in (failure.detail or "")


def test_lifespan_continues_when_gics_unavailable():
    """Regression: a service with no daemon attached must remain usable
    in degraded mode and expose its failure via the property."""
    svc = _make_service()
    svc._cli_path = None
    _REAL_START_DAEMON(svc)
    # Service object is still alive; failure surfaced; nothing raised.
    assert svc.last_start_failure is not None
    assert svc.last_start_failure.reason == "cli_not_found"


def test_system_dependencies_surfaces_gics_failure_reason(test_client):
    """Integration: /ops/system/dependencies must surface gics_failure_reason
    when app.state.gics has a recorded start failure."""
    from tools.gimo_server.main import app

    # Inject a fake gics with a recorded failure into app state.
    fake = MagicMock()
    fake.last_start_failure = GicsStartFailure(
        reason="cli_not_found",
        message="GICS CLI not found at /fake — daemon cannot start.",
        detail="/fake",
    )
    previous = getattr(app.state, "gics", None)
    app.state.gics = fake
    try:
        # Use a token recognized by tests; fall back to env if any.
        import os
        token = os.environ.get("ORCH_TOKEN", "test-token")
        resp = test_client.get(
            "/ops/system/dependencies",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("gics_failure_reason") == "cli_not_found"
        assert "GICS CLI not found" in body.get("gics_failure_message", "")
    finally:
        app.state.gics = previous
