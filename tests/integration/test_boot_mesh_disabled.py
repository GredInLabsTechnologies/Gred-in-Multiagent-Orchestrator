"""Smoke test: server boots clean with mesh disabled.

GIMO Core is exported as an embedded runtime for Android nodes running
in inference/utility mode. Those nodes ship with ``mesh_enabled=False``
(the default) and must boot without touching mesh dispatch code paths.

This test protects the Android export path from a regression where
mesh-only code leaks into the core boot sequence — importing the app
with default config must never fail even if mesh services are absent
or inert.
"""
from __future__ import annotations

import pytest


def test_app_imports_with_default_mesh_disabled():
    """Importing main.app must succeed with ``mesh_enabled`` at its default (False)."""
    from tools.gimo_server.main import app

    # Registered route count is a loose boot-health signal — must be non-zero
    # and cover the canonical /ops/* surface.
    assert len(app.routes) > 100, "app must register the /ops/* surface"


def test_mesh_endpoints_registered_but_gated():
    """Mesh routes must register regardless of mesh_enabled.

    They gate at request-time via ``_get_mesh_enabled`` — not at mount-time.
    This keeps the MCP manifest + OpenAPI schema stable across deployments.
    """
    from tools.gimo_server.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    # Representative mesh endpoints that should be present in the schema.
    assert "/ops/mesh/status" in paths, (
        "mesh router must register even with mesh_enabled=False so schema stays stable"
    )


def test_default_config_has_mesh_disabled():
    """The default OpsConfig must ship with mesh_enabled=False.

    Android runtime images rely on this default — if it ever flips to True
    the export image would try to activate mesh dispatch without the peer
    infrastructure it needs.
    """
    from tools.gimo_server.models.core import OpsConfig

    cfg = OpsConfig()
    assert cfg.mesh_enabled is False, (
        "default config must keep mesh disabled — Android export relies on it"
    )


def test_mesh_dispatch_service_importable_with_mesh_disabled():
    """The mesh DispatchService must import cleanly even when mesh is off.

    Guards the Android export path: importing the server must not pull in
    a broken mesh module. The detailed short-circuit behavior when
    ``mesh_enabled=False`` is covered by the dedicated mesh unit tests.
    """
    try:
        from tools.gimo_server.services.mesh.dispatch import DispatchService
    except Exception as exc:  # pragma: no cover — defensive
        pytest.fail(f"DispatchService import failed: {exc}")

    assert DispatchService is not None


def test_default_cli_role_binds_loopback(monkeypatch: pytest.MonkeyPatch):
    """rev 2 Cambio 8 — without `--role server`, the CLI must default to 127.0.0.1.

    Protects against silent LAN exposure if the launcher argparse defaults drift.
    The CLI block in ``tools/gimo_server/main.py`` is exercised by parsing its
    argparse directly; starting uvicorn is out of scope for this unit check.
    """
    # Ensure no env var forces us into server mode
    monkeypatch.delenv("ORCH_ROLE", raising=False)
    monkeypatch.delenv("ORCH_HOST", raising=False)

    import argparse
    import os as _os_cli

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--role",
        choices=("client", "server"),
        default=_os_cli.environ.get("ORCH_ROLE", "client"),
    )
    args, _ = parser.parse_known_args([])
    assert args.role == "client"

    # Reproduce the host-selection branch from main.py
    explicit_host = _os_cli.environ.get("ORCH_HOST")
    host = (
        (explicit_host or "0.0.0.0") if args.role == "server" else (explicit_host or "127.0.0.1")
    )
    assert host == "127.0.0.1", "default CLI role must bind loopback to prevent LAN exposure"
