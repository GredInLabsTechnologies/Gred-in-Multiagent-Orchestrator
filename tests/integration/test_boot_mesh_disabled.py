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
