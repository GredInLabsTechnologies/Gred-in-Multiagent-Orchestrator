"""Conformance layer fixtures (R20 Cambio 5).

Cross-surface parity harness. Fixtures here boot the FastAPI backend
WITHOUT the ``with TestClient(app) as c:`` context manager (that path
blocks on the real GICS daemon — see MEMORY.md), and register MCP tools
in-process against the same backend via FastMCP.

Two fixtures are exposed:

- ``live_backend``: a ``TestClient`` bound to the FastAPI app after
  calling ``init_governance_subsystem`` explicitly. It reuses the
  session-scoped daemon/license/network mocks from ``tests/conftest.py``
  so no real IPC is performed.
- ``live_mcp_tools``: a ``FastMCP`` instance with every GIMO MCP tool
  registered in-process. Tools call the same singletons as the FastAPI
  process, so an HTTP handler and a registered MCP tool are guaranteed
  to read the same state.
"""
from __future__ import annotations

import os
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def live_backend(
    _mock_gics_daemon,
    _mock_license_guard,
    _mock_lifespan_network,
) -> TestClient:
    """TestClient for the FastAPI app with governance bootstrapped explicitly.

    CRITICAL: this fixture does NOT use ``with TestClient(app) as c:``.
    The memory note in MEMORY.md forbids the context manager because it
    blocks on the real GICS daemon. Instead we instantiate the client
    directly and call ``init_governance_subsystem`` ourselves so the
    shared GICS/storage wiring is identical to the real lifespan.
    """
    from tools.gimo_server.main import app
    from tools.gimo_server.services.bootstrap import (
        init_governance_subsystem,
        reset_for_tests,
    )

    reset_for_tests()
    init_governance_subsystem(start_daemon=False)

    client = TestClient(app, raise_server_exceptions=False)
    yield client


@pytest.fixture(scope="session")
def auth_header() -> Dict[str, str]:
    token = os.environ.get("ORCH_TOKEN", "test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def live_mcp_tools(live_backend) -> Any:
    """Register the real MCP governance tool surface in-process.

    We do NOT spawn a stdio subprocess. FastMCP exposes a ``tool_manager``
    (``_tool_manager`` on older versions) that lets us call tool callables
    directly for parity assertions.
    """
    from mcp.server.fastmcp import FastMCP

    from tools.gimo_server.mcp_bridge.governance_tools import (
        register_governance_tools,
    )

    mcp = FastMCP("gimo-conformance")
    register_governance_tools(mcp)
    return mcp


def _extract_tool_callable(mcp: Any, name: str):
    """Resolve a registered MCP tool by name and return its async callable.

    FastMCP stores tools on an internal tool manager; expose a single
    accessor so the conformance tests stay terse and version-tolerant.
    """
    manager = getattr(mcp, "_tool_manager", None) or getattr(mcp, "tool_manager", None)
    if manager is None:
        raise RuntimeError("FastMCP has no tool_manager (API changed?)")
    tools = getattr(manager, "_tools", None) or getattr(manager, "tools", None) or {}
    tool = tools.get(name)
    if tool is None:
        raise KeyError(f"MCP tool {name!r} not registered")
    # Tool objects expose either .fn, .func, or are callable
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None) or tool
    return fn


@pytest.fixture(scope="session")
def mcp_call(live_mcp_tools):
    """Return an async-awaitable invoker: ``await mcp_call(name, **kwargs)``."""
    async def _call(name: str, **kwargs):
        fn = _extract_tool_callable(live_mcp_tools, name)
        return await fn(**kwargs)
    return _call
