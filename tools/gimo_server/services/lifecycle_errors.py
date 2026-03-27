from __future__ import annotations


class RunNotFoundError(ValueError):
    """Raised when a requested run cannot be proven to exist."""


class LifecycleProofError(RuntimeError):
    """Raised when review/discard lifecycle evidence cannot be proven."""


class PurgeSafetyError(RuntimeError):
    """Raised when purge is refused for safety reasons."""


class PurgeExecutionError(RuntimeError):
    """Raised when purge cleanup or receipt persistence cannot complete."""
