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
    """Return a dict with runtime fingerprints. Consumed by ChaquopyBridge."""
    # `six` is the only pip dep installed in Fase A. If it imports, the
    # Chaquopy pip pipeline is wired correctly and future deps will also work.
    import six  # noqa: F401  — import-to-prove-it-works

    return {
        "ok": "true",
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "impl": platform.python_implementation(),
        "six_imported": "true",
    }


def ping() -> str:
    """Cheap string-only variant for callers that just want a yes/no."""
    return f"pong from cpython {sys.version.split()[0]} on {platform.machine()}"
