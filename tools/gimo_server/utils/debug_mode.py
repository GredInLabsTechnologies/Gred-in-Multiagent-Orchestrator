"""Runtime debug-flag accessor.

The DEBUG env var must be evaluated on each call, not at import time.
Import-time evaluation freezes the flag at first module load and makes
tests that mutate DEBUG (or config.py's dotenv auto-load) unable to
control behaviour downstream.
"""
from __future__ import annotations

import os

_TRUTHY = frozenset({"true", "1", "yes", "verbose"})


def is_debug_mode() -> bool:
    """Return True if the DEBUG env var is truthy at call time."""
    return os.environ.get("DEBUG", "").lower() in _TRUTHY
