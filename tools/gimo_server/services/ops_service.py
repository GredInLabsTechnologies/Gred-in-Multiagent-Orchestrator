# Backward-compatibility shim — real implementation in services/ops/
from __future__ import annotations

from .ops import OpsService  # noqa: F401

__all__ = ["OpsService"]
