"""Chaquopy smoke test — Fase A validation.

Invoked at app boot via ChaquopyBridge.runSmokeTest() to confirm:
  1. libpython3.13.so loads into the JVM process.
  2. The pip-installed wheels (currently just `six`) are importable.
  3. Standard library modules survive the extractPackages="*" step.

When Fase B lands, this file stays as a cheap health-probe the Service
runs before attempting to boot the full GIMO Core via
``tools.gimo_server.main:app``. If smoke() fails, the Service short-circuits
with a clear error instead of spending ~5 s trying to import uvicorn.
"""
from __future__ import annotations

import platform
import sys


def smoke() -> dict[str, str]:
    """Return a dict with runtime fingerprints. Consumed by ChaquopyBridge.

    Exercises the full server-mode stack (Fase B): fastapi → starlette →
    anyio + uvicorn → pydantic v1 shim. If each import resolves, every
    wheel Chaquopy's pip pipeline published is loadable on bionic, and
    uvicorn.run() (the next step in EmbeddedCoreRunner) has a 95%+ chance
    of booting cleanly. The remaining 5% is the network bind + the
    tools.gimo_server import which needs the rove bundle mounted on sys.path.
    """
    # Import chain — ordered intentionally: a failure pinpoints the first
    # wheel missing from the bionic build.
    import fastapi
    import starlette
    import anyio
    import uvicorn
    import click  # uvicorn dep; first pure-Python one after the async stack
    import typing_extensions

    return {
        "ok": "true",
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "impl": platform.python_implementation(),
        "fastapi": getattr(fastapi, "__version__", "?"),
        "starlette": getattr(starlette, "__version__", "?"),
        "uvicorn": getattr(uvicorn, "__version__", "?"),
        "anyio": getattr(anyio, "__version__", "?"),
        "click": getattr(click, "__version__", "?"),
        "typing_extensions": getattr(typing_extensions, "__version__", "?"),
    }


def ping() -> str:
    """Cheap string-only variant for callers that just want a yes/no."""
    return f"pong from cpython {sys.version.split()[0]} on {platform.machine()}"
